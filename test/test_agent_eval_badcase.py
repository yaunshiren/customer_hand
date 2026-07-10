from __future__ import annotations

import json
from datetime import datetime, timezone

from app.eval.badcase import BADCASE_PRIORITY, classify_badcases
from app.eval.models import (
    CaseEvaluationResult,
    CheckResult,
    EvalCase,
    EvalMetrics,
    MetricResult,
)
from app.eval.report import write_eval_reports


def _check(passed: bool) -> CheckResult:
    return CheckResult(applicable=True, passed=passed, expected="expected", actual="actual")


def _result() -> CaseEvaluationResult:
    return CaseEvaluationResult(
        case_id="bad-001",
        trace_id="trace-bad-001",
        user_input="Contact jane@example.com or 13800138000",
        writes_state=False,
        latency_ms=12,
        checks={
            "intent": _check(False),
            "route": _check(False),
            "tool_selection": _check(False),
            "tool_args_complete": _check(False),
            "rag_hit_at_3": _check(False),
            "safety": _check(False),
            "context": _check(False),
            "grounding": _check(False),
        },
        task_success=False,
        answer="Private reply for jane@example.com and 13800138000",
        check_evidence={
            "authorization": "Bearer demo-eval-secret",
            "note": "jane@example.com 13800138000",
        },
    )


def _case() -> EvalCase:
    return EvalCase.model_validate(
        {
            "case_id": "bad-001",
            "user_input": "Contact jane@example.com or 13800138000",
            "expected_intent": "expected",
            "expected_route": "rag",
            "expected_tool": None,
            "expected_args": {},
            "expected_rag_keywords": ["policy"],
            "expected_safety_behavior": "allow",
            "metadata": {"writes_state": False, "scenario": "chat", "setup_turns": []},
        }
    )


def _metrics() -> EvalMetrics:
    failed = MetricResult(numerator=0, denominator=1, value=0.0, not_applicable=False)
    na = MetricResult(numerator=0, denominator=0, value=None, not_applicable=True)
    return EvalMetrics(
        intent_acc=failed,
        route_acc=failed,
        tool_selection_acc=failed,
        tool_args_complete_rate=failed,
        rag_hit_at_3=failed,
        safety_pass_rate=failed,
        task_success_rate=failed,
        avg_latency_ms=12.0,
        avg_latency_not_applicable=False,
    )


def test_badcase_classification_has_stable_priority() -> None:
    result = classify_badcases([_result()])[0]

    assert tuple(result.error_types) == BADCASE_PRIORITY
    assert result.error_type == "UNSAFE_ACTION"


def test_reports_are_sanitized_and_handoff_contains_required_sections(tmp_path) -> None:
    result = classify_badcases([_result()])[0]
    paths = write_eval_reports(
        report_dir=tmp_path,
        run_id="run-001",
        git_commit="commit-001",
        dataset_path=tmp_path / "dataset.jsonl",
        cases=[_case()],
        results=[result],
        metrics=_metrics(),
        secrets=("demo-eval-secret",),
        generated_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )

    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths.values())
    assert "demo-eval-secret" not in combined
    assert "jane@example.com" not in combined
    assert "13800138000" not in combined

    handoff = paths["codex_handoff.md"].read_text(encoding="utf-8")
    assert "Top Badcases" in handoff
    assert "Failed component" in handoff
    assert "Evidence" in handoff
    assert "Likely files" in handoff
    assert "Suggested fix" in handoff
    assert "Tests to add" in handoff
    assert "does not authorize automatic code changes" in handoff

    report = json.loads(paths["eval_report.json"].read_text(encoding="utf-8"))
    assert "user_input" not in report["cases"][0]
    assert "answer" not in report["cases"][0]
    assert report["cases"][0]["answer_present"] is True
    assert report["metrics"]["intent_acc"] == {
        "numerator": 0,
        "denominator": 1,
        "value": 0.0,
        "not_applicable": False,
    }
    assert report["metrics"]["tool_args_complete_rate"]["not_applicable"] is False
