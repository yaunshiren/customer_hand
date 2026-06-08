from __future__ import annotations

from typing import Any

from app.agent.agent import Agent
from app.core.tracker_store import InMemoryTrackerStore
from app.rag.answerer import KnowledgeAnswerer


class FakeKnowledgeAnswerer(KnowledgeAnswerer):
    def __init__(self) -> None:
        pass

    def answer(self, question: str, top_k: int = 3, **_: object) -> dict[str, object]:
        return {
            "question": question,
            "answer": "test invoice policy answer",
            "matches": [],
            "used_llm": False,
        }


def _agent() -> Agent:
    agent = Agent(tracker_store=InMemoryTrackerStore(), flows={})
    agent.llm_generator.client.enabled = False
    agent.knowledge_answerer = FakeKnowledgeAnswerer()
    return agent


def test_acceptance_logistics_query_calls_query_logistics() -> None:
    response = _agent().handle_message(
        "\u67e5\u4e00\u4e0b\u8ba2\u5355 10001 \u5230\u54ea\u4e86",
        "acceptance_logistics_user",
    )
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["business_question_type"] == "logistics_query"
    assert metadata["business_tool"] == "query_logistics"
    assert metadata["tool_name"] == "query_logistics"
    assert metadata["tool_success"] is True
    assert metadata["tool_arguments"] == {"order_id": "10001"}


def test_acceptance_complaint_creates_ticket() -> None:
    response = _agent().handle_message(
        "\u6211\u8981\u6295\u8bc9\u5ba2\u670d\u6001\u5ea6\u5dee",
        "acceptance_ticket_user",
    )
    metadata = response[0]["metadata"]

    assert metadata["route"] == "ticket"
    assert metadata["business_question_type"] == "complaint"
    assert metadata["business_tool"] == "create_ticket"
    assert metadata["tool_name"] == "create_ticket"
    assert metadata["tool_success"] is True
    assert metadata["ticket_id"].startswith("mock_ticket_")


def test_acceptance_invoice_policy_uses_rag() -> None:
    response = _agent().handle_message(
        "\u600e\u4e48\u5f00\u53d1\u7968",
        "acceptance_invoice_policy_user",
    )
    metadata = response[0]["metadata"]

    assert metadata["route"] == "rag"
    assert metadata["business_question_type"] == "invoice_policy"
    assert metadata["business_route"] == "rag"
    assert metadata.get("tool_name") is None
    assert response[0]["text"] == "test invoice policy answer"


def test_acceptance_invoice_creation_confirms_then_calls_create_invoice() -> None:
    agent = _agent()

    first = agent.handle_message(
        "\u8ba2\u5355 10001 \u5f00\u516c\u53f8\u53d1\u7968",
        "acceptance_invoice_user",
    )
    first_metadata = first[0]["metadata"]

    assert first_metadata["route"] == "clarify"
    assert first_metadata["business_question_type"] == "invoice_create"
    assert first_metadata["business_tool"] == "create_invoice"
    assert first_metadata["tool_safety_decision"] == "confirmation_required"
    assert first_metadata.get("tool_name") is None

    second = agent.handle_message("\u786e\u8ba4", "acceptance_invoice_user")
    second_metadata = second[0]["metadata"]

    assert second_metadata["route"] == "tool"
    assert second_metadata["business_source"] == "tool_confirmation"
    assert second_metadata["tool_safety_decision"] == "confirmed"
    assert second_metadata["tool_name"] == "create_invoice"
    assert second_metadata["tool_success"] is True
    assert second_metadata["tool_arguments"] == {"order_id": "10001", "title": "\u516c\u53f8"}


def test_acceptance_tool_failure_degrades_without_crashing() -> None:
    class FailingToolService:
        def query_logistics(self, order_id: str) -> object:
            raise RuntimeError("logistics backend down")

    agent = _agent()
    agent.business_tool_service = FailingToolService()

    response = agent.handle_message(
        "\u67e5\u4e00\u4e0b\u8ba2\u5355 10001 \u5230\u54ea\u4e86",
        "acceptance_tool_failure_user",
    )
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["business_tool"] == "query_logistics"
    assert metadata["tool_name"] == "query_logistics"
    assert metadata["tool_success"] is False
    assert metadata["tool_error_code"] == "TOOL_FAILURE"
    assert "\u6682\u65f6" in response[0]["text"]
