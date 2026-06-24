from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ["LLM_ENABLED"] = "false"

from app.persistence.db import ping_trace_db, trace_db_session  # noqa: E402
from app.persistence.models import AgentTrace  # noqa: E402
from main import app  # noqa: E402


class FakeAgent:
    def handle_message(
        self,
        message: str,
        sender_id: str,
        conversation_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            {
                "recipient_id": sender_id,
                "text": "售后政策回答",
                "metadata": {
                    "route": "rag",
                    "rewritten_query": "售后政策",
                    "intentLeafIds": ["S14_售后政策"],
                    "memory_snapshot": {
                        "recent_turns": [],
                        "memory_entities": {
                            "product": "",
                            "order_id": "",
                            "intent": "policy",
                        },
                        "summary": "",
                    },
                    "query_rewrite": {
                        "original_query": "我想问售后政策",
                        "rewritten_query": "售后政策",
                        "memory_entities": {
                            "product": "",
                            "order_id": "",
                            "intent": "policy",
                        },
                        "rewrite_applied": True,
                        "reason": "test_trace",
                    },
                    "intentConfidence": 0.88,
                },
            }
        ]


class FailingAgent:
    def handle_message(
        self,
        message: str,
        sender_id: str,
        conversation_id: str | None = None,
    ) -> list[dict[str, object]]:
        raise RuntimeError("agent exploded")


class CapturingTraceRecorder:
    def __init__(self) -> None:
        self.starts: list[dict[str, object]] = []
        self.successes: list[dict[str, object]] = []
        self.errors: list[dict[str, object]] = []

    def record_message_start(self, **kwargs) -> None:
        self.starts.append(dict(kwargs))

    def record_message_success(self, **kwargs) -> None:
        self.successes.append(dict(kwargs))

    def record_message_error(self, **kwargs) -> None:
        self.errors.append(dict(kwargs))


@pytest.fixture(autouse=True)
def restore_app_state():
    original_agent = app.state.agent
    original_trace_recorder = app.state.trace_recorder
    try:
        yield
    finally:
        app.state.agent = original_agent
        app.state.trace_recorder = original_trace_recorder


@pytest.fixture()
def trace_db_available() -> None:
    try:
        ping_trace_db()
    except Exception as exc:  # pragma: no cover - depends on local MySQL.
        pytest.skip(f"trace database is not available: {exc}")


def _trace_id() -> str:
    return f"test_{uuid.uuid4().hex}"


def _delete_agent_trace(trace_id: str) -> None:
    with trace_db_session() as session:
        row = session.get(AgentTrace, trace_id)
        if row is not None:
            session.delete(row)


def _get_agent_trace(trace_id: str) -> AgentTrace | None:
    with trace_db_session() as session:
        row = session.get(AgentTrace, trace_id)
        if row is None:
            return None
        return AgentTrace(
            id=row.id,
            sender_id=row.sender_id,
            conversation_id=row.conversation_id,
            user_text=row.user_text,
            rewritten_query=row.rewritten_query,
            memory_snapshot=row.memory_snapshot,
            intent_id=row.intent_id,
            intent_confidence=row.intent_confidence,
            route=row.route,
            final_answer=row.final_answer,
            latency_ms=row.latency_ms,
            created_at=row.created_at,
        )


def test_api_messages_calls_trace_recorder_success_without_db() -> None:
    trace_id = _trace_id()
    recorder = CapturingTraceRecorder()
    app.state.agent = FakeAgent()
    app.state.trace_recorder = recorder
    client = TestClient(app)

    response = client.post(
        "/api/messages",
        headers={"X-Trace-Id": trace_id},
        json={"sender_id": "trace_user", "message": "我想问售后政策"},
    )

    assert response.status_code == 200
    assert recorder.starts[0]["trace_id"] == trace_id
    assert recorder.starts[0]["sender_id"] == "trace_user"
    assert recorder.successes[0]["trace_id"] == trace_id
    assert recorder.successes[0]["memory_snapshot"]["memory_entities"]["intent"] == "policy"
    assert recorder.successes[0]["memory_snapshot"]["query_rewrite"] == {
        "original_query": "我想问售后政策",
        "rewritten_query": "售后政策",
        "memory_entities": {
            "product": "",
            "order_id": "",
            "intent": "policy",
        },
        "rewrite_applied": True,
        "reason": "test_trace",
    }
    assert recorder.successes[0]["rewritten_query"] == "售后政策"
    assert recorder.successes[0]["intent_id"] == "S14_售后政策"
    assert recorder.successes[0]["route"] == "rag"
    assert recorder.successes[0]["final_answer"] == "售后政策回答"
    assert recorder.errors == []


def test_api_messages_calls_trace_recorder_on_agent_error_without_db() -> None:
    trace_id = _trace_id()
    recorder = CapturingTraceRecorder()
    app.state.agent = FailingAgent()
    app.state.trace_recorder = recorder
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/messages",
        headers={"X-Trace-Id": trace_id},
        json={"sender_id": "trace_error_user", "message": "触发异常"},
    )

    assert response.status_code == 500
    assert recorder.starts[0]["trace_id"] == trace_id
    assert recorder.errors[0]["trace_id"] == trace_id
    assert isinstance(recorder.errors[0]["error"], RuntimeError)
    assert recorder.successes == []


def test_api_messages_persists_agent_trace(trace_db_available) -> None:
    trace_id = _trace_id()
    _delete_agent_trace(trace_id)
    app.state.agent = FakeAgent()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/messages",
            headers={"X-Trace-Id": trace_id},
            json={"sender_id": "trace_user", "message": "我想问售后政策"},
        )

        assert response.status_code == 200
        row = _get_agent_trace(trace_id)
        assert row is not None
        assert row.id == trace_id
        assert row.sender_id == "trace_user"
        assert row.conversation_id == "trace_user"
        assert row.user_text == "我想问售后政策"
        assert row.rewritten_query == "售后政策"
        assert row.memory_snapshot["query_rewrite"]["original_query"] == "我想问售后政策"
        assert row.memory_snapshot["query_rewrite"]["rewritten_query"] == "售后政策"
        assert row.memory_snapshot["query_rewrite"]["memory_entities"]["intent"] == "policy"
        assert row.memory_snapshot["query_rewrite"]["rewrite_applied"] is True
        assert row.intent_id == "S14_售后政策"
        assert row.intent_confidence == pytest.approx(0.88)
        assert row.route == "rag"
        assert row.final_answer == "售后政策回答"
        assert row.latency_ms is not None
    finally:
        _delete_agent_trace(trace_id)


def test_api_messages_persists_error_trace(trace_db_available) -> None:
    trace_id = _trace_id()
    _delete_agent_trace(trace_id)
    app.state.agent = FailingAgent()
    client = TestClient(app, raise_server_exceptions=False)

    try:
        response = client.post(
            "/api/messages",
            headers={"X-Trace-Id": trace_id},
            json={"sender_id": "trace_error_user", "message": "触发异常"},
        )

        assert response.status_code == 500
        row = _get_agent_trace(trace_id)
        assert row is not None
        assert row.sender_id == "trace_error_user"
        assert row.route == "error"
        assert row.final_answer is not None
        assert "RuntimeError: agent exploded" in row.final_answer
        assert row.latency_ms is not None
    finally:
        _delete_agent_trace(trace_id)
