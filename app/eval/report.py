from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.entry.security import redact_text

from .badcase import BADCASE_PRIORITY
from .models import CaseEvaluationResult, EvalCase, EvalMetrics


REPORT_FILENAMES = (
    "eval_report.md",
    "eval_report.json",
    "badcases.jsonl",
    "codex_handoff.md",
)

ERROR_GUIDANCE: dict[str, dict[str, Any]] = {
    "INTENT_ERROR": {
        "component": "intent",
        "files": ["app/intent/", "data/intents/"],
        "fix": "Review intent taxonomy, examples, and deterministic classifier evidence.",
        "tests": ["test/test_intent_classifier.py", "test/test_agent_intent_routing.py"],
    },
    "ROUTE_ERROR": {
        "component": "route",
        "files": ["app/intent/policy.py", "app/agent/graph/node_routing.py"],
        "fix": "Review the route policy contract for the predicted intent.",
        "tests": ["test/test_route_policy.py", "test/test_agent_intent_route_policy.py"],
    },
    "RAG_MISS": {
        "component": "retrieval",
        "files": ["app/rag/", "data/knowledge/", "app/memory/query_rewrite.py"],
        "fix": "Inspect top retrieval evidence, query rewrite, metadata, and rerank ordering.",
        "tests": ["test/test_hybrid_retriever.py", "test/test_rag_retrieval_trace.py"],
    },
    "TOOL_SELECTION_ERROR": {
        "component": "tool_selection",
        "files": ["app/tools/", "app/agent/graph/node_tooling.py"],
        "fix": "Review tool descriptions and the boundary between policy questions and actions.",
        "tests": ["test/test_agent_tool_routing.py", "test/test_tool_calling_acceptance.py"],
    },
    "TOOL_ARGUMENT_ERROR": {
        "component": "tool_arguments",
        "files": ["app/tools/schemas.py", "app/agent/graph/node_tooling.py"],
        "fix": "Review required argument extraction and missing-field clarification.",
        "tests": ["test/test_tool_schemas.py", "test/test_mock_business_tools.py"],
    },
    "CONTEXT_LOST": {
        "component": "memory_context",
        "files": ["app/memory/", "app/agent/graph/node_context.py"],
        "fix": "Inspect the setup-turn memory snapshot and final query rewrite evidence.",
        "tests": ["test/test_memory_context.py", "test/test_memory_service.py"],
    },
    "UNSAFE_ACTION": {
        "component": "safety",
        "files": ["app/entry/", "app/agent/tool_safety.py", "app/skills/"],
        "fix": "Review security flags, confirmation, authorization, and write-action blocking.",
        "tests": ["test/test_api_entry_guard.py", "test/test_agent_tool_safety.py"],
    },
    "ANSWER_UNGROUNDED": {
        "component": "answer_grounding",
        "files": ["app/rag/answerer.py", "app/agent/graph/node_response.py"],
        "fix": "Require response citations to link to retrieved trace evidence.",
        "tests": ["test/test_rag_context_citation.py", "test/test_agent_llm_behavior.py"],
    },
}


def write_eval_reports(
    *,
    report_dir: Path,
    run_id: str,
    git_commit: str,
    dataset_path: Path,
    cases: list[EvalCase],
    results: list[CaseEvaluationResult],
    metrics: EvalMetrics,
    secrets: Iterable[str] = (),
    generated_at: datetime | None = None,
) -> dict[str, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    generated = generated_at or datetime.now(timezone.utc)
    case_by_id = {case.case_id: case for case in cases}
    badcases = [result for result in results if result.error_type]
    error_counts = Counter(
        error_type
        for result in badcases
        for error_type in result.error_types
    )
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": generated.isoformat(),
        "git_commit": git_commit,
        "dataset": str(dataset_path).replace("\\", "/"),
        "case_count": len(results),
        "writes_state_case_count": sum(result.writes_state for result in results),
        "writes_state_case_ids": [result.case_id for result in results if result.writes_state],
        "metrics": metrics.model_dump(mode="json"),
        "badcase_count": len(badcases),
        "badcase_counts": dict(sorted(error_counts.items())),
        "cases": [_case_report_row(result) for result in results],
        "grounding_scope": "deterministic citation/retrieval evidence contract; no semantic fact judge",
    }
    safe_summary = sanitize_report_value(summary, secrets=secrets)
    badcase_rows = [
        _badcase_row(result, case_by_id[result.case_id])
        for result in badcases
    ]
    safe_badcases = sanitize_report_value(badcase_rows, secrets=secrets)

    contents = {
        "eval_report.json": json.dumps(safe_summary, ensure_ascii=False, indent=2) + "\n",
        "eval_report.md": render_eval_markdown(safe_summary),
        "badcases.jsonl": "".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in safe_badcases
        ),
        "codex_handoff.md": render_codex_handoff(
            safe_summary,
            safe_badcases,
        ),
    }
    _assert_report_contents_safe(contents, secrets=secrets)
    paths: dict[str, Path] = {}
    for name in REPORT_FILENAMES:
        path = report_dir / name
        temp_path = report_dir / f".{name}.tmp"
        temp_path.write_text(contents[name], encoding="utf-8")
        temp_path.replace(path)
        paths[name] = path
    return paths


def sanitize_report_value(value: Any, *, secrets: Iterable[str] = ()) -> Any:
    clean_secrets = tuple(str(secret) for secret in secrets if str(secret))
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in {"authorization", "api_key", "x_api_key", "headers", "token"}:
                sanitized[str(key)] = "<redacted>"
            else:
                sanitized[str(key)] = sanitize_report_value(item, secrets=clean_secrets)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_report_value(item, secrets=clean_secrets) for item in value]
    if isinstance(value, str):
        text = value
        for secret in clean_secrets:
            text = text.replace(secret, "<redacted-secret>")
        return redact_text(text)
    return value


def render_eval_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Agent Eval Report",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Git commit: `{summary['git_commit']}`",
        f"- Cases: `{summary['case_count']}`",
        f"- Writes state: `{summary['writes_state_case_count']}`",
        "",
        "## Metrics",
        "",
        "| Metric | Numerator | Denominator | Value |",
        "|---|---:|---:|---:|",
    ]
    for name, metric in summary["metrics"].items():
        if not isinstance(metric, dict):
            continue
        value = "not_applicable" if metric.get("not_applicable") else _format_metric(metric.get("value"))
        lines.append(
            f"| `{name}` | {metric.get('numerator', '-')} | {metric.get('denominator', '-')} | {value} |"
        )
    avg = summary["metrics"].get("avg_latency_ms")
    avg_text = "not_applicable" if summary["metrics"].get("avg_latency_not_applicable") else f"{float(avg):.2f} ms"
    lines.extend(
        [
            f"| `avg_latency_ms` | - | {summary['case_count']} | {avg_text} |",
            "",
            "## Badcases",
            "",
            "| Error Type | Count |",
            "|---|---:|",
        ]
    )
    if summary["badcase_counts"]:
        for name, count in summary["badcase_counts"].items():
            lines.append(f"| `{name}` | {count} |")
    else:
        lines.append("| `-` | 0 |")
    lines.extend(
        [
            "",
            "## Grounding Scope",
            "",
            "`ANSWER_UNGROUNDED` only checks deterministic retrieval/citation evidence linkage. "
            "It does not judge complete semantic factual correctness.",
            "",
        ]
    )
    return "\n".join(lines)


def render_codex_handoff(
    summary: dict[str, Any],
    badcases: list[dict[str, Any]],
    *,
    top_k: int = 10,
) -> str:
    priority = {name: index for index, name in enumerate(BADCASE_PRIORITY)}
    ranked = sorted(
        badcases,
        key=lambda row: (
            priority.get(str(row.get("error_type")), len(priority)),
            str(row.get("case_id")),
        ),
    )[:top_k]
    lines = [
        "# Codex Handoff",
        "",
        "This document is input for a reviewed follow-up repair round. It does not authorize automatic code changes.",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Task success: `{_metric_value(summary['metrics']['task_success_rate'])}`",
        f"- Badcases: `{summary['badcase_count']}`",
        "",
        "## Top Badcases",
        "",
    ]
    if not ranked:
        lines.extend(["No badcases were produced.", ""])
        return "\n".join(lines)
    for index, row in enumerate(ranked, start=1):
        lines.extend(
            [
                f"### {index}. `{row['case_id']}` — `{row['error_type']}`",
                "",
                f"- Failed component: `{row['failed_component']}`",
                f"- Trace ID: `{row['trace_id']}`",
                f"- Writes state: `{str(row['writes_state']).lower()}`",
                f"- Evidence: `{_inline_json(row['evidence'])}`",
                f"- Likely files: {', '.join(f'`{item}`' for item in row['likely_files'])}",
                f"- Suggested fix: {row['suggested_fix']}",
                f"- Tests to add: {', '.join(f'`{item}`' for item in row['tests_to_add'])}",
                "",
            ]
        )
    return "\n".join(lines)


def _badcase_row(result: CaseEvaluationResult, case: EvalCase) -> dict[str, Any]:
    error_type = str(result.error_type)
    guidance = ERROR_GUIDANCE[error_type]
    failed_checks = {
        name: check.model_dump(mode="json")
        for name, check in result.checks.items()
        if check.applicable and check.passed is False
    }
    return {
        "case_id": result.case_id,
        "trace_id": result.trace_id,
        "error_type": error_type,
        "error_types": result.error_types,
        "failed_component": guidance["component"],
        "writes_state": result.writes_state,
        "expected_intent": case.expected_intent,
        "actual_intent": result.actual_intent,
        "expected_route": case.expected_route,
        "actual_route": result.actual_route,
        "expected_tool": case.expected_tool,
        "actual_tools": result.actual_tools,
        "evidence": {
            "failed_checks": failed_checks,
            "retrieved_doc_ids": result.retrieved_doc_ids,
            **result.check_evidence,
        },
        "likely_files": guidance["files"],
        "suggested_fix": guidance["fix"],
        "tests_to_add": guidance["tests"],
    }


def _case_report_row(result: CaseEvaluationResult) -> dict[str, Any]:
    row = result.model_dump(
        mode="json",
        exclude={"user_input", "answer"},
    )
    row["answer_present"] = bool(str(result.answer or "").strip())
    return row


def _assert_report_contents_safe(contents: dict[str, str], *, secrets: Iterable[str]) -> None:
    for secret in (str(item) for item in secrets if str(item)):
        if any(secret in content for content in contents.values()):
            raise ValueError("report sanitization failed: secret remained in generated output")


def _format_metric(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def _metric_value(metric: dict[str, Any]) -> str:
    if metric.get("not_applicable"):
        return "not_applicable"
    return _format_metric(metric.get("value"))


def _inline_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:1200].replace("`", "'")
