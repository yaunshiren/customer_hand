from __future__ import annotations

import pytest

from app.core.tracker import DialogueStateTracker
from app.intent import BusinessQuestionClassifier, IntentCandidate, IntentResult


def _intent(intent_id: str, intent_name: str, intent_type: str) -> IntentResult:
    return IntentResult(
        intent_id=intent_id,
        intent_name=intent_name,
        intent_type=intent_type,  # type: ignore[arg-type]
        confidence=0.9,
        candidates=[IntentCandidate(intent_id=intent_id, confidence=0.9)],
        source="llm_classifier",
    )


@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        ("保修政策是怎样的", "policy"),
        ("怎么开发票", "invoice_policy"),
        ("下单后一般多久发货", "policy"),
    ],
)
def test_policy_questions_route_to_rag(text: str, expected_type: str) -> None:
    result = BusinessQuestionClassifier().classify(text)

    assert result.question_type == expected_type
    assert result.route == "rag"
    assert result.requires_rag is True
    assert result.target_tool is None


def test_logistics_query_with_order_id_targets_logistics_tool() -> None:
    result = BusinessQuestionClassifier().classify("查一下订单 10001 到哪了")

    assert result.question_type == "logistics_query"
    assert result.route == "tool"
    assert result.target_tool == "query_logistics"
    assert result.extracted_arguments == {"order_id": "10001"}
    assert result.missing_arguments == []


def test_logistics_query_without_order_id_requires_clarification() -> None:
    result = BusinessQuestionClassifier().classify("帮我查一下物流")

    assert result.question_type == "logistics_query"
    assert result.route == "clarify"
    assert result.target_tool == "query_logistics"
    assert result.missing_arguments == ["order_id"]


def test_order_query_with_order_id_targets_order_tool() -> None:
    result = BusinessQuestionClassifier().classify("帮我查询订单 10001 的状态")

    assert result.question_type == "order_query"
    assert result.route == "tool"
    assert result.target_tool == "query_order"
    assert result.extracted_arguments == {"order_id": "10001"}


def test_complaint_targets_ticket_tool_with_context() -> None:
    result = BusinessQuestionClassifier().classify("我要投诉客服态度差", user_id="u-001")

    assert result.question_type == "complaint"
    assert result.route == "ticket"
    assert result.target_tool == "create_ticket"
    assert result.extracted_arguments["category"] == "complaint"
    assert result.extracted_arguments["description"] == "我要投诉客服态度差"
    assert result.extracted_arguments["user_id"] == "u-001"
    assert result.missing_arguments == []


def test_invoice_create_with_order_id_and_company_title_targets_invoice_tool() -> None:
    result = BusinessQuestionClassifier().classify("订单 10001 开公司发票")

    assert result.question_type == "invoice_create"
    assert result.route == "tool"
    assert result.target_tool == "create_invoice"
    assert result.extracted_arguments == {"order_id": "10001", "title": "公司"}
    assert result.requires_confirmation is True
    assert result.risk_level == "medium"


def test_invoice_create_missing_title_requires_clarification() -> None:
    result = BusinessQuestionClassifier().classify("订单 10001 开发票")

    assert result.question_type == "invoice_create"
    assert result.route == "clarify"
    assert result.target_tool == "create_invoice"
    assert result.extracted_arguments == {"order_id": "10001"}
    assert result.missing_arguments == ["title"]


def test_invoice_title_supports_common_title_phrase() -> None:
    result = BusinessQuestionClassifier().classify("订单 10001 开发票，抬头是上海测试科技有限公司")

    assert result.route == "tool"
    assert result.target_tool == "create_invoice"
    assert result.extracted_arguments == {"order_id": "10001", "title": "上海测试科技有限公司"}


def test_bare_order_id_can_be_extracted_in_logistics_context() -> None:
    result = BusinessQuestionClassifier().classify("帮我查一下 10001 到哪了")

    assert result.route == "tool"
    assert result.target_tool == "query_logistics"
    assert result.extracted_arguments == {"order_id": "10001"}


def test_order_id_can_come_from_tracker_slot() -> None:
    tracker = DialogueStateTracker("u-002")
    tracker.set_slot("order_id", "A12345678")

    result = BusinessQuestionClassifier().classify("帮我查一下物流", tracker=tracker)

    assert result.route == "tool"
    assert result.target_tool == "query_logistics"
    assert result.extracted_arguments == {"order_id": "A12345678"}


def test_intent_result_can_drive_policy_classification() -> None:
    result = BusinessQuestionClassifier().classify(
        "这台手机保修多久",
        intent_result=_intent("S14_售后政策", "售后政策", "KB"),
    )

    assert result.question_type == "policy"
    assert result.route == "rag"
    assert result.signals[1] == "intent:S14_售后政策"
