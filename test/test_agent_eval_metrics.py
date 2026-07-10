from __future__ import annotations

from app.eval.badcase import classify_badcases
from app.eval.metrics import calculate_metrics, evaluate_case
from app.eval.models import (
    AgentTraceEvidence,
    EvalCase,
    HttpEvidence,
    RetrievalTraceEvidence,
    ToolTraceEvidence,
    TraceEvidence,
)


def _case(**overrides):
    values = {
        "case_id": "case-001",
        "user_input": "query",
        "expected_intent": "S14_售后政策",
        "expected_route": "rag",
        "expected_tool": None,
        "expected_args": {},
        "expected_rag_keywords": ["保修期"],
        "expected_safety_behavior": "allow",
        "metadata": {"writes_state": False, "scenario": "chat", "setup_turns": []},
    }
    values.update(overrides)
    return EvalCase.model_validate(values)


def _evidence(**overrides):
    values = {
        "trace_id": "trace-001",
        "agent": AgentTraceEvidence(
            trace_id="trace-001",
            intent_id="S14_售后政策",
            route="rag",
            rewritten_query="小米 14 Pro 保修期",
            final_answer="保修说明",
            latency_ms=25,
        ),
        "retrieval": [
            RetrievalTraceEvidence(
                channel="keyword",
                doc_id="POLICY_WAR_001",
                chunk_id="POLICY_WAR_001-0",
                score=8.0,
                content="商品保修期和保修范围说明",
            )
        ],
        "tools": [],
        "http": HttpEvidence(
            status_code=200,
            latency_ms=30,
            response_items=[
                {
                    "text": "保修说明",
                    "metadata": {
                        "route": "rag",
                        "security_flags": {"prompt_injection_risk": False},
                        "citations": [{"doc_id": "POLICY_WAR_001"}],
                    },
                }
            ],
        ),
    }
    values.update(overrides)
    return TraceEvidence.model_validate(values)


def test_metrics_include_numerator_denominator_and_value() -> None:
    result = evaluate_case(_case(), _evidence())
    metrics = calculate_metrics([result])

    assert result.task_success is True
    assert metrics.intent_acc.model_dump() == {
        "numerator": 1,
        "denominator": 1,
        "value": 1.0,
        "not_applicable": False,
    }
    assert metrics.rag_hit_at_3.numerator == 1
    assert metrics.task_success_rate.value == 1.0
    assert metrics.avg_latency_ms == 25.0


def test_zero_denominator_is_not_applicable() -> None:
    case = _case(
        expected_intent=None,
        expected_route="chitchat",
        expected_rag_keywords=[],
    )
    evidence = _evidence(
        agent=AgentTraceEvidence(
            trace_id="trace-001",
            route="chitchat",
            final_answer="hello",
            latency_ms=10,
        ),
        retrieval=[],
        http=HttpEvidence(
            status_code=200,
            latency_ms=12,
            response_items=[{"text": "hello", "metadata": {"security_flags": {}}}],
        ),
    )

    metrics = calculate_metrics([evaluate_case(case, evidence)])

    assert metrics.intent_acc.denominator == 0
    assert metrics.intent_acc.value is None
    assert metrics.intent_acc.not_applicable is True
    assert metrics.rag_hit_at_3.not_applicable is True


def test_tool_args_completeness_scores_keys_not_redacted_values() -> None:
    case = _case(
        expected_intent=None,
        expected_route="tool",
        expected_tool="create_ticket",
        expected_args={"category": "complaint", "description": "private"},
        expected_rag_keywords=[],
    )
    tool = ToolTraceEvidence(
        tool_name="create_ticket",
        arguments={
            "category": "complaint",
            "description": {"sha256": "hash", "redacted": True},
        },
        status="success",
    )
    evidence = _evidence(
        agent=AgentTraceEvidence(trace_id="trace-001", route="tool", final_answer="created", latency_ms=8),
        retrieval=[],
        tools=[tool],
        http=HttpEvidence(
            status_code=200,
            latency_ms=9,
            response_items=[{"text": "created", "metadata": {"tool_name": "create_ticket", "security_flags": {}}}],
        ),
    )

    result = evaluate_case(case, evidence)

    assert result.checks["tool_selection"].passed is True
    assert result.checks["tool_args_complete"].passed is True
    assert result.checks["tool_args_complete"].evidence["value_comparison"].startswith("not_scored")


def test_answer_ungrounded_is_only_deterministic_evidence_failure() -> None:
    evidence = _evidence(
        http=HttpEvidence(
            status_code=200,
            latency_ms=30,
            response_items=[{"text": "answer", "metadata": {"security_flags": {}}}],
        )
    )

    result = classify_badcases([evaluate_case(_case(), evidence)])[0]

    assert result.checks["rag_hit_at_3"].passed is True
    assert result.checks["grounding"].passed is False
    assert "ANSWER_UNGROUNDED" in result.error_types
    assert result.checks["grounding"].evidence["semantic_fact_correctness_judged"] is False

