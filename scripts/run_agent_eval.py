from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.eval.badcase import classify_badcases  # noqa: E402
from app.eval.evidence import EvidenceProvider, MySQLEvidenceProvider  # noqa: E402
from app.eval.metrics import calculate_metrics, evaluate_case  # noqa: E402
from app.eval.models import (  # noqa: E402
    EvalCase,
    EvalInfrastructureError,
    HttpEvidence,
    TraceEvidence,
)
from app.eval.report import write_eval_reports  # noqa: E402


DEFAULT_DATASET = PROJECT_ROOT / "data" / "eval" / "customer_service_eval.jsonl"
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports"
MIN_EVAL_CASES = 20


class HttpResponse(Protocol):
    status_code: int
    headers: Any
    text: str

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> HttpResponse: ...

    def post(self, url: str, **kwargs: Any) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    base_url: str
    reports_dir: Path
    request_timeout_seconds: float = 30.0
    max_rate_limit_retries: int = 2
    max_retry_after_seconds: int = 60


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic customer_hand Agent eval through /api/messages and correlate "
            "agent_trace, retrieval_trace, and tool_trace by X-Trace-Id."
        )
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--trace-wait-seconds", type=float, default=5.0)
    parser.add_argument("--max-rate-limit-retries", type=int, default=2)
    parser.add_argument("--max-retry-after-seconds", type=int, default=60)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        all_cases = load_eval_cases(args.dataset)
        selected = select_cases(all_cases, case_ids=args.case_id, limit=args.limit)
        if args.validate_only:
            print(
                f"validated {len(all_cases)} eval cases from {_display_path(args.dataset)}; "
                f"selected={len(selected)}"
            )
            return 0

        api_key = str(os.getenv("EVAL_API_KEY") or "").strip()
        if not api_key:
            raise EvalInfrastructureError(
                "EVAL_API_KEY is required in the environment for a real eval run"
            )

        config = RunnerConfig(
            base_url=str(args.base_url).rstrip("/"),
            reports_dir=args.reports_dir,
            request_timeout_seconds=max(0.1, float(args.request_timeout_seconds)),
            max_rate_limit_retries=max(0, int(args.max_rate_limit_retries)),
            max_retry_after_seconds=max(1, int(args.max_retry_after_seconds)),
        )
        provider = MySQLEvidenceProvider(
            wait_timeout_seconds=max(0.1, float(args.trace_wait_seconds)),
        )
        summary = run_eval(
            selected,
            config=config,
            api_key=api_key,
            http_client=requests,
            evidence_provider=provider,
        )
    except (EvalInfrastructureError, FileNotFoundError, ValueError) as exc:
        print(f"eval failed: {exc}", file=sys.stderr)
        print("no reports were generated for this failed run", file=sys.stderr)
        return 2

    print(
        f"eval complete: run_id={summary['run_id']} cases={summary['case_count']} "
        f"badcases={summary['badcase_count']}"
    )
    for name, path in summary["report_paths"].items():
        print(f"  {name}: {_display_path(path)}")
    return 0


def load_eval_cases(path: Path, *, minimum_cases: int = MIN_EVAL_CASES) -> list[EvalCase]:
    if not path.exists():
        raise FileNotFoundError(f"eval dataset not found: {path}")
    cases: list[EvalCase] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} is not valid JSON") from exc
            try:
                case = EvalCase.model_validate(raw)
            except Exception as exc:
                raise ValueError(f"{path}:{line_no} is not a valid eval case: {exc}") from exc
            if case.case_id in seen:
                raise ValueError(f"duplicate eval case_id: {case.case_id}")
            seen.add(case.case_id)
            cases.append(case)
    if len(cases) < minimum_cases:
        raise ValueError(
            f"eval dataset must contain at least {minimum_cases} cases; found {len(cases)}"
        )
    return cases


def select_cases(
    cases: list[EvalCase],
    *,
    case_ids: Sequence[str],
    limit: int | None,
) -> list[EvalCase]:
    selected = list(cases)
    requested = {str(case_id).strip() for case_id in case_ids if str(case_id).strip()}
    if requested:
        known = {case.case_id for case in cases}
        missing = sorted(requested - known)
        if missing:
            raise ValueError(f"unknown eval case_id(s): {', '.join(missing)}")
        selected = [case for case in selected if case.case_id in requested]
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be at least 1")
        selected = selected[:limit]
    if not selected:
        raise ValueError("no eval cases selected")
    return selected


def run_eval(
    cases: list[EvalCase],
    *,
    config: RunnerConfig,
    api_key: str,
    http_client: HttpClient,
    evidence_provider: EvidenceProvider,
    sleep: Callable[[float], None] = time.sleep,
    run_id: str | None = None,
    git_commit: str | None = None,
    dataset_path: Path = DEFAULT_DATASET,
) -> dict[str, Any]:
    if not str(api_key or "").strip():
        raise EvalInfrastructureError("EVAL_API_KEY is required for a real eval run")
    _preflight_api(config, http_client=http_client)
    evidence_provider.preflight()

    resolved_run_id = run_id or _new_run_id()
    results = []
    for case in cases:
        identity = _case_identity(resolved_run_id, case.case_id)
        for setup_index, setup_text in enumerate(case.metadata.setup_turns, start=1):
            _post_message(
                case=case,
                message=setup_text,
                identity=identity,
                api_key=api_key,
                config=config,
                http_client=http_client,
                sleep=sleep,
                turn_label=f"setup-{setup_index}",
                scenario="chat",
                writes_state=False,
            )

        http, trace_id = _post_message(
            case=case,
            message=case.user_input,
            identity=identity,
            api_key=api_key,
            config=config,
            http_client=http_client,
            sleep=sleep,
            turn_label="score",
            scenario=case.metadata.scenario,
            writes_state=case.metadata.writes_state,
        )
        requirements = _trace_requirements(http)
        agent, retrieval, tools = evidence_provider.fetch(
            trace_id,
            require_retrieval=requirements["require_retrieval"],
            require_tool=requirements["require_tool"],
        )
        evidence = TraceEvidence(
            trace_id=trace_id,
            agent=agent,
            retrieval=retrieval,
            tools=tools,
            http=http,
        )
        results.append(evaluate_case(case, evidence))

    classified = classify_badcases(results)
    metrics = calculate_metrics(classified)
    report_paths = write_eval_reports(
        report_dir=config.reports_dir,
        run_id=resolved_run_id,
        git_commit=git_commit or _git_commit(),
        dataset_path=dataset_path,
        cases=cases,
        results=classified,
        metrics=metrics,
        secrets=(api_key,),
    )
    return {
        "run_id": resolved_run_id,
        "case_count": len(classified),
        "badcase_count": sum(bool(result.error_type) for result in classified),
        "metrics": metrics,
        "results": classified,
        "report_paths": report_paths,
    }


def _preflight_api(config: RunnerConfig, *, http_client: HttpClient) -> None:
    try:
        response = http_client.get(
            f"{config.base_url}/health",
            timeout=config.request_timeout_seconds,
        )
    except Exception as exc:
        raise EvalInfrastructureError(
            f"API service is unavailable at {config.base_url}; start it before running eval"
        ) from exc
    if response.status_code != 200:
        raise EvalInfrastructureError(
            f"API health check failed with HTTP {response.status_code}"
        )


def _post_message(
    *,
    case: EvalCase,
    message: str,
    identity: dict[str, str],
    api_key: str,
    config: RunnerConfig,
    http_client: HttpClient,
    sleep: Callable[[float], None],
    turn_label: str,
    scenario: str,
    writes_state: bool,
) -> tuple[HttpEvidence, str]:
    request_trace_id = f"eval-{uuid.uuid4().hex}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Trace-Id": request_trace_id,
    }
    if writes_state:
        headers["Idempotency-Key"] = f"eval-{uuid.uuid4().hex}"
    payload = {
        "sender_id": identity["sender_id"],
        "conversation_id": identity["conversation_id"],
        "message": message,
        "source": "api",
        "scenario": scenario,
        "metadata": {
            "eval_run_id": identity["run_id"],
            "eval_case_id": case.case_id,
            "eval_turn": turn_label,
            "writes_state": writes_state,
        },
    }

    attempts = 0
    while True:
        started_at = time.perf_counter()
        try:
            response = http_client.post(
                f"{config.base_url}/api/messages",
                json=payload,
                headers=headers,
                timeout=config.request_timeout_seconds,
            )
        except Exception as exc:
            raise EvalInfrastructureError(
                f"API request failed for case_id={case.case_id} turn={turn_label}"
            ) from exc
        latency_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        if response.status_code != 429:
            break
        if attempts >= config.max_rate_limit_retries:
            raise EvalInfrastructureError(
                f"RATE_LIMITED: case_id={case.case_id} exceeded "
                f"max retries={config.max_rate_limit_retries}"
            )
        attempts += 1
        retry_after = _retry_after_seconds(response)
        sleep(min(retry_after, config.max_retry_after_seconds))

    trace_id = str(response.headers.get("X-Trace-Id") or "").strip()
    if not trace_id:
        raise EvalInfrastructureError(
            f"API response missing X-Trace-Id for case_id={case.case_id} turn={turn_label}"
        )
    body = _response_json(response, case_id=case.case_id, turn_label=turn_label)
    if response.status_code != 200:
        error_code = body.get("error_code") if isinstance(body, dict) else None
        raise EvalInfrastructureError(
            f"API returned HTTP {response.status_code} for case_id={case.case_id} "
            f"turn={turn_label} error_code={error_code or 'unknown'}"
        )
    if not isinstance(body, list) or not all(isinstance(item, dict) for item in body):
        raise EvalInfrastructureError(
            f"API returned an invalid message response for case_id={case.case_id}"
        )
    return (
        HttpEvidence(
            status_code=response.status_code,
            latency_ms=latency_ms,
            response_items=[dict(item) for item in body],
            error_body=None,
        ),
        trace_id,
    )


def _response_json(response: HttpResponse, *, case_id: str, turn_label: str) -> Any:
    try:
        return response.json()
    except Exception as exc:
        raise EvalInfrastructureError(
            f"API returned non-JSON content for case_id={case_id} turn={turn_label}"
        ) from exc


def _trace_requirements(http: HttpEvidence) -> dict[str, bool]:
    metadata = _last_metadata(http.response_items)
    require_retrieval = bool(
        metadata.get("rag_match_count")
        or metadata.get("rag_doc_ids")
        or metadata.get("citations")
    )
    require_tool = bool(
        metadata.get("tool_name")
        or metadata.get("ticket_id")
        or (
            metadata.get("source") in {"tool", "ticket"}
            and metadata.get("tool_safety_decision") != "pending_confirmation"
        )
    )
    return {
        "require_retrieval": require_retrieval,
        "require_tool": require_tool,
    }


def _last_metadata(items: list[dict[str, Any]]) -> dict[str, Any]:
    for item in reversed(items):
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            return dict(metadata)
    return {}


def _retry_after_seconds(response: HttpResponse) -> int:
    raw = response.headers.get("Retry-After")
    try:
        return max(1, int(float(raw)))
    except (TypeError, ValueError):
        return 1


def _case_identity(run_id: str, case_id: str) -> dict[str, str]:
    token = uuid.uuid4().hex[:10]
    safe_case = "".join(char if char.isalnum() else "-" for char in case_id)[:48]
    return {
        "run_id": run_id,
        "sender_id": f"eval-{safe_case}-{token}",
        "conversation_id": f"eval-conv-{safe_case}-{token}",
    }


def _new_run_id() -> str:
    return f"agent-eval-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


if __name__ == "__main__":
    raise SystemExit(main())

