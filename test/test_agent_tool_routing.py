from __future__ import annotations

import pytest

from app.agent.agent import Agent
from app.core.tracker_store import InMemoryTrackerStore
from app.rag.answerer import KnowledgeAnswerer
from tracker_test_support import trusted_test_principal


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


def _handle(agent: Agent, message: str, sender_id: str):
    return agent.handle_message(
        message,
        sender_id,
        principal=trusted_test_principal(sender_id),
    )


def test_logistics_query_with_order_id_calls_business_tool() -> None:
    response = _handle(_agent(), "查一下订单 10001 到哪了", "tool_logistics_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["business_question_type"] == "logistics_query"
    assert metadata["business_tool"] == "query_logistics"
    assert metadata["tool_name"] == "query_logistics"
    assert metadata["tool_success"] is True
    assert metadata["tool_arguments"] == {"order_id": "10001"}
    assert "10001" in response[0]["text"]


def test_order_status_query_is_not_overridden_by_logistics_rag_route() -> None:
    response = _handle(_agent(), "帮我查询订单 10001 的状态", "tool_order_status_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["business_question_type"] == "order_query"
    assert metadata["business_tool"] == "query_order"
    assert metadata["tool_name"] == "query_order"
    assert metadata["tool_arguments"] == {"order_id": "10001"}


@pytest.mark.parametrize(
    "message",
    [
        "帮我查订单 10001 的物流到哪里了",
        "订单 10002 的快递状态和运单号是什么？",
    ],
)
def test_realtime_logistics_query_overrides_generic_logistics_rag_route(message: str) -> None:
    response = _handle(_agent(), message, "tool_logistics_eval_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["business_question_type"] == "logistics_query"
    assert metadata["business_tool"] == "query_logistics"
    assert metadata["tool_name"] == "query_logistics"


def test_ticket_current_status_query_calls_ticket_status_tool() -> None:
    response = _handle(
        _agent(),
        "请查询工单 TKT-20260709-FFFFFFFFFFFF 当前状态",
        "tool_ticket_status_user",
    )
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["business_question_type"] == "ticket_status_query"
    assert metadata["business_tool"] == "query_ticket_status"
    assert metadata["tool_name"] == "query_ticket_status"
    assert metadata["tool_arguments"] == {"ticket_no": "TKT-20260709-FFFFFFFFFFFF"}


@pytest.mark.parametrize(
    "followup",
    ["查一下物流", "那它现在到哪里了？", "配送进度怎么样"],
)
def test_logistics_followup_inherits_order_id_and_calls_tool(followup: str) -> None:
    agent = _agent()
    sender_id = "tool_logistics_context_user"

    _handle(agent, "请记住我的订单号是 10001", sender_id)
    response = _handle(agent, followup, sender_id)
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["business_tool"] == "query_logistics"
    assert metadata["tool_name"] == "query_logistics"
    assert metadata["tool_arguments"] == {"order_id": "10001"}


@pytest.mark.parametrize(
    "message",
    [
        "发货多久到",
        "下单后多久发货",
        "怎么修改地址",
        "物流怎么处理",
    ],
)
def test_logistics_policy_questions_stay_on_rag(message: str) -> None:
    response = _handle(_agent(), message, "tool_policy_negative_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "rag"
    assert metadata.get("tool_name") is None


@pytest.mark.parametrize("message", ["如何提交工单", "工单怎么处理"])
def test_general_ticket_questions_do_not_call_ticket_status_tool(message: str) -> None:
    response = _handle(_agent(), message, "tool_ticket_negative_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] != "tool"
    assert metadata.get("tool_name") is None


def test_logistics_query_without_order_id_uses_rag_and_exposes_missing_argument() -> None:
    response = _handle(_agent(), "帮我查一下物流", "tool_clarify_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "rag"
    assert metadata["business_question_type"] == "logistics_query"
    assert metadata["business_route"] == "clarify"
    assert metadata["business_missing_arguments"] == ["order_id"]
    assert metadata.get("tool_name") is None
    assert response[0]["text"] == "测试知识库回答"


def test_complaint_creates_ticket_through_business_tool() -> None:
    response = _handle(_agent(), "我要投诉客服态度差", "tool_ticket_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "ticket"
    assert metadata["business_question_type"] == "complaint"
    assert metadata["business_tool"] == "create_ticket"
    assert metadata["tool_name"] == "create_ticket"
    assert metadata["tool_success"] is True
    assert metadata["ticket_id"]
    assert "工单" in response[0]["text"]


def test_invoice_policy_uses_rag_instead_of_tool() -> None:
    response = _handle(_agent(), "怎么开发票", "tool_invoice_policy_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "rag"
    assert metadata["business_question_type"] == "invoice_policy"
    assert metadata["business_route"] == "rag"
    assert metadata.get("tool_name") is None
    assert response[0]["text"] == "测试知识库回答"


def test_invoice_create_with_required_arguments_requires_confirmation() -> None:
    response = _handle(_agent(), "订单 10001 开公司发票", "tool_invoice_user")
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
    response = _handle(_agent(), "查一下订单 99999 到哪了", "tool_failure_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["business_tool"] == "query_logistics"
    assert metadata["tool_name"] == "query_logistics"
    assert metadata["tool_success"] is False
    assert metadata["tool_error_code"] == "ORDER_NOT_FOUND"
    assert "没有查到" in response[0]["text"]
