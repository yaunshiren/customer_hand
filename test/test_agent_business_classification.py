from __future__ import annotations

import pytest

from app.agent.agent import Agent
from app.core.tracker_store import InMemoryTrackerStore
from app.intent import IntentCandidate, IntentResult
from app.rag.answerer import KnowledgeAnswerer


def _intent(intent_id: str, intent_name: str, intent_type: str) -> IntentResult:
    return IntentResult(
        intent_id=intent_id,
        intent_name=intent_name,
        intent_type=intent_type,  # type: ignore[arg-type]
        confidence=0.9,
        candidates=[IntentCandidate(intent_id=intent_id, confidence=0.9)],
        source="llm_classifier",
    )


class FakeIntentClassifier:
    def __init__(self, mapping: dict[str, IntentResult]) -> None:
        self.mapping = mapping

    def classify(self, text: str) -> IntentResult:
        return self.mapping.get(text, _intent("UNKNOWN", "未知", "UNKNOWN"))


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


INTENTS = {
    "查一下订单 10001 到哪了": _intent("S16_物流配送", "物流配送", "KB_TOOL"),
    "订单 10001 开公司发票": _intent("S17_发票会员", "发票会员", "KB_TOOL"),
    "我要投诉客服态度差": _intent("F3_投诉吐槽", "投诉吐槽", "TICKET"),
}


def _agent() -> Agent:
    agent = Agent(tracker_store=InMemoryTrackerStore(), flows={})
    agent.llm_generator.client.enabled = False
    agent.intent_classifier = FakeIntentClassifier(INTENTS)
    agent.knowledge_answerer = FakeKnowledgeAnswerer()
    return agent


@pytest.mark.parametrize(
    ("message", "question_type", "business_route", "tool", "arguments"),
    [
        ("查一下订单 10001 到哪了", "logistics_query", "tool", "query_logistics", {"order_id": "10001"}),
        ("订单 10001 开公司发票", "invoice_create", "tool", "create_invoice", {"order_id": "10001", "title": "公司"}),
        (
            "我要投诉客服态度差",
            "complaint",
            "ticket",
            "create_ticket",
            {"category": "complaint", "description": "我要投诉客服态度差", "user_id": "business_user"},
        ),
    ],
)
def test_agent_response_metadata_exposes_business_classification(
    message: str,
    question_type: str,
    business_route: str,
    tool: str,
    arguments: dict[str, str],
) -> None:
    response = _agent().handle_message(message, "business_user")
    metadata = response[0]["metadata"]

    assert metadata["business_question_type"] == question_type
    assert metadata["business_route"] == business_route
    assert metadata["business_tool"] == tool
    assert metadata["business_extracted_arguments"] == arguments
    assert metadata["business_missing_arguments"] == []
