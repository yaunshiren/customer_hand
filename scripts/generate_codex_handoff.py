#!/usr/bin/env python3
"""Generate reports/codex_handoff.md from eval summary and badcases.

This script is intentionally lightweight and self-contained. It can consume a
badcases JSONL file exported by existing eval scripts and produce a handoff
markdown file that Codex can use for the next focused repair pass.

Typical usage:

    python scripts/generate_codex_handoff.py \
      --badcases reports/badcases.jsonl \
      --output reports/codex_handoff.md

Expected badcase JSONL fields are flexible. The script looks for common keys:
case_id, question/user_input/input, expected_behavior, expected_intent,
predicted_intent, expected_tool, actual_tool/predicted_tool, expected_args,
actual_args, error_type, trace_id, answer/actual_answer, evidence, suggested_fix.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_BADCASES = Path("reports/badcases.jsonl")
DEFAULT_OUTPUT = Path("reports/codex_handoff.md")
DEFAULT_EVAL_REPORT = Path("reports/eval_report.json")

ERROR_TO_FILES: dict[str, list[str]] = {
    "INTENT_ERROR": ["app/intent/", "app/agent/graph/node_understanding.py", "data/intents/"],
    "ROUTE_ERROR": ["app/intent/policy.py", "app/agent/graph/node_routing.py"],
    "RAG_MISS": ["app/rag/", "data/knowledge/", "app/memory/query_rewrite.py"],
    "ANSWER_UNGROUNDED": ["app/rag/answerer.py", "app/agent/graph/node_response.py", "app/llm/prompts.py"],
    "TOOL_SELECTION_ERROR": ["app/tools/", "app/agent/graph/node_tooling.py", "app/agent/tool_safety.py"],
    "TOOL_ARGUMENT_ERROR": ["app/tools/schemas.py", "app/tools/service.py", "app/agent/graph/node_tooling.py"],
    "TOOL_FAILURE": ["app/tools/service.py", "app/tools/mock_store.py", "app/persistence/tool_recorder.py"],
    "CONTEXT_LOST": ["app/memory/", "app/agent/graph/node_context.py", "app/agent/graph/node_tracker.py"],
    "UNSAFE_ACTION": ["app/entry/", "app/agent/tool_safety.py", "app/tools/"],
    "PROMPT_INJECTION_RISK": ["app/entry/security.py", "app/llm/prompts.py"],
    "FORMAT_ERROR": ["app/llm/client.py", "app/llm/prompts.py", "app/tools/schemas.py"],
    "UNKNOWN": ["app/agent/graph/", "app/persistence/"],
}

ERROR_TO_TESTS: dict[str, list[str]] = {
    "INTENT_ERROR": ["test/test_intent_classifier.py", "test/test_agent_intent_routing.py"],
    "ROUTE_ERROR": ["test/test_route_policy.py", "test/test_agent_intent_route_policy.py"],
    "RAG_MISS": ["test/test_hybrid_retriever.py", "test/test_vector_rag.py", "test/test_rag_retrieval_trace.py"],
    "ANSWER_UNGROUNDED": ["test/test_rag_context_citation.py", "test/test_agent_llm_behavior.py"],
    "TOOL_SELECTION_ERROR": ["test/test_agent_tool_routing.py", "test/test_tool_calling_acceptance.py"],
    "TOOL_ARGUMENT_ERROR": ["test/test_tool_schemas.py", "test/test_mock_business_tools.py"],
    "TOOL_FAILURE": ["test/test_agent_tool_degradation.py", "test/test_tool_trace.py"],
    "CONTEXT_LOST": ["test/test_memory_context.py", "test/test_memory_service.py"],
    "UNSAFE_ACTION": ["test/test_agent_tool_safety.py", "test/test_api_entry_guard.py"],
    "PROMPT_INJECTION_RISK": ["test/test_entry_security.py", "test/test_api_entry_guard.py"],
    "FORMAT_ERROR": ["test/test_llm_client_json_contract.py"],
    "UNKNOWN": ["test/"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Codex handoff markdown from badcases.")
    parser.add_argument("--badcases", type=Path, default=DEFAULT_BADCASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--eval-report", type=Path, default=DEFAULT_EVAL_REPORT)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    badcases = read_jsonl(args.badcases) if args.badcases.exists() else []
    eval_summary = read_json(args.eval_report) if args.eval_report.exists() else {}
    markdown = render_handoff(
        badcases=badcases,
        eval_summary=eval_summary,
        badcase_source=args.badcases,
        top_k=args.top_k,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    print(f"Wrote {args.output} with {len(badcases)} badcase(s).")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} is not valid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no} must be a JSON object")
            rows.append(row)
    return rows


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    return value if isinstance(value, dict) else {"value": value}


def render_handoff(
    *,
    badcases: list[dict[str, Any]],
    eval_summary: dict[str, Any],
    badcase_source: Path,
    top_k: int,
) -> str:
    error_counts = Counter(normalize_error_type(row.get("error_type")) for row in badcases)
    ranked = sorted(
        badcases,
        key=lambda row: (
            priority(normalize_error_type(row.get("error_type"))),
            str(row.get("case_id", "")),
        ),
    )[:top_k]

    lines: list[str] = [
        "# Codex Handoff",
        "",
        f"Generated at: `{datetime.now().isoformat(timespec='seconds')}`",
        f"Badcase source: `{badcase_source}`",
        "",
        "## 1. Current Eval Summary",
        "",
    ]

    if eval_summary:
        lines.extend(render_eval_summary(eval_summary))
    else:
        lines.extend(
            [
                "No machine-readable eval summary was found.",
                "",
                "Expected optional file: `reports/eval_report.json`.",
            ]
        )

    lines.extend([
        "",
        "## 2. Badcase Distribution",
        "",
        "| Error Type | Count |",
        "|---|---:|",
    ])
    if error_counts:
        for error_type, count in sorted(error_counts.items()):
            lines.append(f"| `{md(error_type)}` | {count} |")
    else:
        lines.append("| `-` | 0 |")

    lines.extend([
        "",
        "## 3. Top Badcases",
        "",
    ])
    if not ranked:
        lines.append("No badcases found. If eval failed, generate `reports/badcases.jsonl` first.")
    for index, row in enumerate(ranked, start=1):
        lines.extend(render_badcase(index, row))

    lines.extend([
        "",
        "## 4. Required Codex Workflow",
        "",
        "When using Codex to fix these issues, follow this sequence:",
        "",
        "1. Read the relevant trace and files first; do not edit immediately.",
        "2. Pick one error type per repair pass.",
        "3. Propose a minimal change plan.",
        "4. Add or update tests/eval cases before or with the fix.",
        "5. Run `python -m compileall app main.py scripts test` and `pytest -q`.",
        "6. Rerun eval and compare metrics.",
        "7. Update docs if behavior changes.",
        "",
        "## 5. Acceptance Criteria",
        "",
        "- All existing tests pass.",
        "- New or modified badcases have tests or eval cases.",
        "- No unrelated large refactor is introduced.",
        "- Agent trace, retrieval trace, and tool trace remain available for debugging.",
        "- High-risk tool paths still require confirmation and idempotency.",
        "- Metrics do not regress without a documented reason.",
        "",
    ])
    return "\n".join(lines)


def render_eval_summary(summary: dict[str, Any]) -> list[str]:
    lines = ["| Metric | Value |", "|---|---:|"]
    for key, value in sorted(summary.items()):
        if isinstance(value, (str, int, float, bool)) or value is None:
            lines.append(f"| `{md(key)}` | `{md(value)}` |")
    if len(lines) == 2:
        lines.append("| `-` | `No scalar metrics found` |")
    return lines


def render_badcase(index: int, row: dict[str, Any]) -> list[str]:
    error_type = normalize_error_type(row.get("error_type"))
    files = ERROR_TO_FILES.get(error_type, ERROR_TO_FILES["UNKNOWN"])
    tests = ERROR_TO_TESTS.get(error_type, ERROR_TO_TESTS["UNKNOWN"])
    case_id = pick(row, "case_id", "id", default=f"badcase_{index:03d}")
    user_input = pick(row, "user_input", "question", "query", "input", default="")
    expected = pick(row, "expected_behavior", "expected", "expected_answer", default="")
    actual = pick(row, "actual_behavior", "answer", "actual_answer", "response", default="")
    trace_id = pick(row, "trace_id", "traceId", default="")
    evidence = pick(row, "evidence", "reason", "failure_reason", "reasons", default="")
    suggested_fix = pick(row, "suggested_fix", "fix", "recommendation", default="")

    return [
        f"### BADCASE-{index:03d}: `{md(case_id)}`",
        "",
        f"- Error type: `{md(error_type)}`",
        f"- Trace ID: `{md(trace_id or '-')}`",
        f"- User input: {block(user_input)}",
        f"- Expected: {block(expected)}",
        f"- Actual: {block(actual)}",
        f"- Evidence: {block(evidence)}",
        f"- Suggested fix: {block(suggested_fix or default_fix_for(error_type))}",
        f"- Files likely affected: {', '.join(f'`{md(file)}`' for file in files)}",
        f"- Tests to add/update: {', '.join(f'`{md(test)}`' for test in tests)}",
        "",
    ]


def pick(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return value
    return default


def normalize_error_type(value: Any) -> str:
    if value is None or value == "":
        return "UNKNOWN"
    text = str(value).strip().upper()
    aliases = {
        "HALLUCINATION": "ANSWER_UNGROUNDED",
        "GENERATION_HALLUCINATION": "ANSWER_UNGROUNDED",
        "RETRIEVAL_MISS": "RAG_MISS",
        "ARGUMENT_ERROR": "TOOL_ARGUMENT_ERROR",
        "TOOL_ARGS_ERROR": "TOOL_ARGUMENT_ERROR",
        "SAFETY_ERROR": "UNSAFE_ACTION",
    }
    return aliases.get(text, text)


def priority(error_type: str) -> int:
    order = {
        "UNSAFE_ACTION": 0,
        "PROMPT_INJECTION_RISK": 1,
        "TOOL_FAILURE": 2,
        "TOOL_ARGUMENT_ERROR": 3,
        "TOOL_SELECTION_ERROR": 4,
        "CONTEXT_LOST": 5,
        "RAG_MISS": 6,
        "ANSWER_UNGROUNDED": 7,
        "INTENT_ERROR": 8,
        "ROUTE_ERROR": 9,
        "FORMAT_ERROR": 10,
        "UNKNOWN": 99,
    }
    return order.get(error_type, 50)


def default_fix_for(error_type: str) -> str:
    suggestions = {
        "INTENT_ERROR": "Review intent taxonomy and add representative eval cases; adjust classifier prompt or rule fallback.",
        "ROUTE_ERROR": "Review route policy and add route regression tests.",
        "RAG_MISS": "Inspect retrieval trace; consider query rewrite, BM25 + vector hybrid retrieval, rerank, or chunk metadata fixes.",
        "ANSWER_UNGROUNDED": "Strengthen answer prompt to cite retrieved context and refuse unsupported claims.",
        "TOOL_SELECTION_ERROR": "Clarify tool descriptions and add tool selection eval cases.",
        "TOOL_ARGUMENT_ERROR": "Tighten Pydantic schema, slot extraction, and missing-field clarification.",
        "TOOL_FAILURE": "Add timeout/error handling tests and inspect mock/domain service behavior.",
        "CONTEXT_LOST": "Persist pending task state and add multi-turn continuation tests.",
        "UNSAFE_ACTION": "Add entry guard / tool safety checks, confirmation, idempotency, and authorization tests.",
        "PROMPT_INJECTION_RISK": "Add prompt injection patterns and safety regression cases.",
        "FORMAT_ERROR": "Constrain model output schema and add parser tests.",
    }
    return suggestions.get(error_type, "Inspect trace evidence and add a regression eval case before fixing.")


def block(value: Any) -> str:
    if value is None or value == "":
        return "`-`"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, indent=2)
    else:
        text = str(value)
    text = text.strip()
    if "\n" in text or len(text) > 120:
        return "\n\n```text\n" + text[:1200] + "\n```"
    return f"`{md(text)}`"


def md(value: Any) -> str:
    text = str(value)
    return text.replace("`", "'").replace("|", "/")


if __name__ == "__main__":
    main()
