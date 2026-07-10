from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.eval.evidence import MySQLEvidenceProvider
from app.eval.models import (
    AgentTraceEvidence,
    EvalCase,
    EvalInfrastructureError,
    ToolTraceEvidence,
)
from scripts import run_agent_eval


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        body: Any,
        *,
        trace_id: str = "trace-response-001",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = body
        self.text = "response"
        self.headers = {"X-Trace-Id": trace_id, **(headers or {})}

    def json(self) -> Any:
        return self._body


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.posts: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(200, {"status": "ok"}, trace_id="health")

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.posts.append({"url": url, **kwargs})
        return self.responses.pop(0)


class FakeEvidenceProvider:
    def __init__(self, *, fail_fetch: bool = False) -> None:
        self.preflight_called = False
        self.fetches: list[tuple[str, bool, bool]] = []
        self.fail_fetch = fail_fetch

    def preflight(self) -> None:
        self.preflight_called = True

    def fetch(self, trace_id: str, *, require_retrieval: bool, require_tool: bool):
        self.fetches.append((trace_id, require_retrieval, require_tool))
        if self.fail_fetch:
            raise EvalInfrastructureError("incomplete trace evidence")
        return (
            AgentTraceEvidence(
                trace_id=trace_id,
                route="chitchat",
                final_answer="hello",
                latency_ms=7,
            ),
            [],
            [],
        )


def _case(**overrides: Any) -> EvalCase:
    values = {
        "case_id": "case-001",
        "user_input": "hello",
        "expected_intent": None,
        "expected_route": "chitchat",
        "expected_tool": None,
        "expected_args": {},
        "expected_rag_keywords": [],
        "expected_safety_behavior": "allow",
        "metadata": {"writes_state": False, "scenario": "chat", "setup_turns": []},
    }
    values.update(overrides)
    return EvalCase.model_validate(values)


def _config(report_dir: Path, **overrides: Any) -> run_agent_eval.RunnerConfig:
    values = {
        "base_url": "http://127.0.0.1:8000",
        "reports_dir": report_dir,
        "request_timeout_seconds": 1.0,
        "max_rate_limit_retries": 1,
        "max_retry_after_seconds": 1,
    }
    values.update(overrides)
    return run_agent_eval.RunnerConfig(**values)


def test_runner_calls_messages_and_correlates_response_trace(tmp_path) -> None:
    client = FakeHttpClient(
        [
            FakeResponse(
                200,
                [{"text": "hello", "metadata": {"route": "chitchat", "security_flags": {}}}],
                trace_id="trace-from-response",
            )
        ]
    )
    provider = FakeEvidenceProvider()

    summary = run_agent_eval.run_eval(
        [_case()],
        config=_config(tmp_path),
        api_key="demo-eval-secret",
        http_client=client,
        evidence_provider=provider,
        run_id="run-test",
        git_commit="commit-test",
    )

    assert provider.preflight_called is True
    assert provider.fetches == [("trace-from-response", False, False)]
    assert client.posts[0]["url"].endswith("/api/messages")
    assert client.posts[0]["headers"]["Authorization"] == "Bearer demo-eval-secret"
    assert summary["case_count"] == 1
    assert summary["metrics"].task_success_rate.value == 1.0
    combined = "\n".join(path.read_text(encoding="utf-8") for path in summary["report_paths"].values())
    assert "demo-eval-secret" not in combined


def test_writes_state_requests_get_unique_identity_and_idempotency_key(tmp_path) -> None:
    responses = [
        FakeResponse(200, [{"text": "ok", "metadata": {"security_flags": {}}}], trace_id="trace-1"),
        FakeResponse(200, [{"text": "ok", "metadata": {"security_flags": {}}}], trace_id="trace-2"),
    ]
    client = FakeHttpClient(responses)
    case_one = _case(
        case_id="write-001",
        expected_route="chitchat",
        expected_tool="create_ticket",
        metadata={"writes_state": True, "scenario": "ticket", "setup_turns": []},
    )
    case_two = _case(
        case_id="write-002",
        expected_route="chitchat",
        expected_tool="create_ticket",
        metadata={"writes_state": True, "scenario": "ticket", "setup_turns": []},
    )
    provider = FakeEvidenceProvider()

    run_agent_eval.run_eval(
        [case_one, case_two],
        config=_config(tmp_path),
        api_key="secret",
        http_client=client,
        evidence_provider=provider,
        run_id="run-write",
        git_commit="commit-test",
    )

    keys = [post["headers"]["Idempotency-Key"] for post in client.posts]
    senders = [post["json"]["sender_id"] for post in client.posts]
    conversations = [post["json"]["conversation_id"] for post in client.posts]
    assert len(set(keys)) == 2
    assert len(set(senders)) == 2
    assert len(set(conversations)) == 2
    assert all(post["json"]["metadata"]["writes_state"] is True for post in client.posts)


def test_rate_limit_retries_are_bounded(tmp_path) -> None:
    client = FakeHttpClient(
        [
            FakeResponse(429, {"error_code": "rate_limited"}, headers={"Retry-After": "9"}),
            FakeResponse(429, {"error_code": "rate_limited"}, headers={"Retry-After": "9"}),
        ]
    )
    sleeps: list[float] = []

    with pytest.raises(EvalInfrastructureError, match="RATE_LIMITED"):
        run_agent_eval.run_eval(
            [_case()],
            config=_config(tmp_path, max_rate_limit_retries=1, max_retry_after_seconds=2),
            api_key="secret",
            http_client=client,
            evidence_provider=FakeEvidenceProvider(),
            sleep=sleeps.append,
            run_id="run-rate",
            git_commit="commit-test",
        )

    assert sleeps == [2]
    assert len(client.posts) == 2
    assert not list(tmp_path.glob("*"))


def test_incomplete_trace_does_not_generate_reports(tmp_path) -> None:
    client = FakeHttpClient(
        [FakeResponse(200, [{"text": "hello", "metadata": {"security_flags": {}}}])]
    )

    with pytest.raises(EvalInfrastructureError, match="incomplete trace"):
        run_agent_eval.run_eval(
            [_case()],
            config=_config(tmp_path),
            api_key="secret",
            http_client=client,
            evidence_provider=FakeEvidenceProvider(fail_fetch=True),
            run_id="run-infra",
            git_commit="commit-test",
        )

    assert not list(tmp_path.glob("*"))


def test_mysql_provider_fails_closed_when_trace_is_incomplete(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.eval.evidence._read_trace_bundle",
        lambda trace_id: (None, [], []),
    )
    provider = MySQLEvidenceProvider(
        wait_timeout_seconds=0.02,
        poll_interval_seconds=0.005,
    )

    with pytest.raises(EvalInfrastructureError, match="incomplete trace evidence"):
        provider.fetch("trace-missing", require_retrieval=True, require_tool=True)


def test_mysql_provider_preflight_reports_unavailable_database(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.eval.evidence.ping_trace_db",
        lambda: (_ for _ in ()).throw(ConnectionError("db down")),
    )

    with pytest.raises(EvalInfrastructureError, match="trace MySQL is unavailable"):
        MySQLEvidenceProvider().preflight()


def test_api_preflight_failure_does_not_create_reports(tmp_path) -> None:
    class OfflineClient(FakeHttpClient):
        def get(self, url: str, **kwargs: Any) -> FakeResponse:
            raise ConnectionError("offline")

    with pytest.raises(EvalInfrastructureError, match="API service is unavailable"):
        run_agent_eval.run_eval(
            [_case()],
            config=_config(tmp_path),
            api_key="secret",
            http_client=OfflineClient([]),
            evidence_provider=FakeEvidenceProvider(),
            run_id="run-offline",
            git_commit="commit-test",
        )

    assert not list(tmp_path.glob("*"))


def test_missing_response_trace_header_is_infrastructure_error(tmp_path) -> None:
    response = FakeResponse(200, [{"text": "ok", "metadata": {"security_flags": {}}}])
    response.headers = {}
    client = FakeHttpClient([response])

    with pytest.raises(EvalInfrastructureError, match="missing X-Trace-Id"):
        run_agent_eval.run_eval(
            [_case()],
            config=_config(tmp_path),
            api_key="secret",
            http_client=client,
            evidence_provider=FakeEvidenceProvider(),
            run_id="run-no-trace",
            git_commit="commit-test",
        )

    assert not list(tmp_path.glob("*"))


def test_main_requires_eval_api_key_without_contacting_services(monkeypatch) -> None:
    monkeypatch.delenv("EVAL_API_KEY", raising=False)

    assert run_agent_eval.main(["--limit", "1"]) == 2


def test_parser_does_not_accept_api_key_argument() -> None:
    option_strings = {
        option
        for action in run_agent_eval.build_parser()._actions
        for option in action.option_strings
    }

    assert "--api-key" not in option_strings
