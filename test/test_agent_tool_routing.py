from __future__ import annotations

from app.agent.agent import Agent
from app.core.tracker_store import InMemoryTrackerStore
from app.rag.answerer import KnowledgeAnswerer


class FakeKnowledgeAnswerer(KnowledgeAnswerer):
    def __init__(self) -> None:
        pass

    def answer(self, question: str, top_k: int = 3, **_: object) -> dict[str, object]:
        return {
            "question": question,
            "answer": "测试知识库回答",
            "matches": [],
            "used_llm": False,
        }


def _agent() -> Agent:
    agent = Agent(tracker_store=InMemoryTrackerStore(), flows={})
    agent.llm_generator.client.enabled = False
    agent.knowledge_answerer = FakeKnowledgeAnswerer()
    return agent


def test_logistics_query_with_order_id_calls_business_tool() -> None:
    response = _agent().handle_message("查一下订单 10001 到哪了", "tool_logistics_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["business_question_type"] == "logistics_query"
    assert metadata["business_tool"] == "query_logistics"
    assert metadata["tool_name"] == "query_logistics"
    assert metadata["tool_success"] is True
    assert metadata["tool_arguments"] == {"order_id": "10001"}
    assert "10001" in response[0]["text"]


def test_logistics_query_without_order_id_asks_for_missing_argument() -> None:
    response = _agent().handle_message("帮我查一下物流", "tool_clarify_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "clarify"
    assert metadata["business_question_type"] == "logistics_query"
    assert metadata["business_route"] == "clarify"
    assert metadata["business_missing_arguments"] == ["order_id"]
    assert metadata.get("tool_name") is None
    assert "订单号" in response[0]["text"]


def test_complaint_creates_ticket_through_business_tool() -> None:
    response = _agent().handle_message("我要投诉客服态度差", "tool_ticket_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "ticket"
    assert metadata["business_question_type"] == "complaint"
    assert metadata["business_tool"] == "create_ticket"
    assert metadata["tool_name"] == "create_ticket"
    assert metadata["tool_success"] is True
    assert metadata["ticket_id"].startswith("mock_ticket_")
    assert "工单" in response[0]["text"]


def test_invoice_policy_uses_rag_instead_of_tool() -> None:
    response = _agent().handle_message("怎么开发票", "tool_invoice_policy_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "rag"
    assert metadata["business_question_type"] == "invoice_policy"
    assert metadata["business_route"] == "rag"
    assert metadata.get("tool_name") is None
    assert response[0]["text"] == "测试知识库回答"


def test_invoice_create_with_required_arguments_requires_confirmation() -> None:
    response = _agent().handle_message("订单 10001 开公司发票", "tool_invoice_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "clarify"
    assert metadata["business_question_type"] == "invoice_create"
    assert metadata["business_tool"] == "create_invoice"
    assert metadata["business_requires_confirmation"] is True
    assert metadata.get("tool_name") is None
    assert metadata["tool_safety_decision"] == "confirmation_required"
    assert "发票" in response[0]["text"]
    assert "确认" in response[0]["text"]


def test_tool_failure_returns_friendly_response_without_crashing() -> None:
    response = _agent().handle_message("查一下订单 99999 到哪了", "tool_failure_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["business_tool"] == "query_logistics"
    assert metadata["tool_name"] == "query_logistics"
    assert metadata["tool_success"] is False
    assert metadata["tool_error_code"] == "ORDER_NOT_FOUND"
    assert "没有查到" in response[0]["text"]
