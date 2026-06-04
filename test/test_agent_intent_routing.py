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
        confidence=0.91,
        candidates=[IntentCandidate(intent_id=intent_id, confidence=0.91)],
        reason="验收用例分类",
        source="llm_classifier",
    )


class FakeIntentClassifier:
    def __init__(self, mapping: dict[str, IntentResult]) -> None:
        self.mapping = mapping

    def classify(self, text: str) -> IntentResult:
        return self.mapping[text]


class FakeKnowledgeAnswerer(KnowledgeAnswerer):
    def __init__(self) -> None:
        pass

    def answer(self, question: str, top_k: int = 3, **_: object) -> dict[str, object]:
        return {
            "question": question,
            "answer": "测试知识库回答：先说明政策或排查步骤，再引导用户补充必要信息。",
            "matches": [],
            "used_llm": False,
        }


INTENT_CASES = {
    "我的扫地机充不进电了": _intent("F1_故障报告", "故障报告", "KB_TICKET"),
    "希望 APP 能加个深色模式": _intent("F2_功能建议", "功能建议", "TICKET"),
    "扫地机能不能加个语音播报关闭功能": _intent("F2_功能建议", "功能建议", "TICKET"),
    "客服态度太差了": _intent("F3_投诉吐槽", "投诉吐槽", "TICKET"),
    "我能改收货地址吗？已经发货了": _intent("S16_物流配送", "物流配送", "KB_TOOL"),
    "小米 14 Pro 保修期多久？": _intent("S14_售后政策", "售后政策", "KB"),
    "小米 14 Pro 用什么充电器？": _intent("S6_配件兼容", "配件兼容", "KB"),
    "苹果 15 Pro 怎么样？": _intent("C2_越界提问", "越界提问", "CHITCHAT"),
}


def _agent() -> tuple[Agent, InMemoryTrackerStore]:
    store = InMemoryTrackerStore()
    agent = Agent(tracker_store=store, flows={})
    agent.llm_generator.client.enabled = False
    agent.intent_classifier = FakeIntentClassifier(INTENT_CASES)
    agent.knowledge_answerer = FakeKnowledgeAnswerer()
    return agent, store


@pytest.mark.parametrize(
    ("case_id", "message", "route", "system_route", "requires_rag", "rag_match_count"),
    [
        ("F1-01", "我的扫地机充不进电了", "rag", "kb_ticket", True, 0),
        ("F2-01", "希望 APP 能加个深色模式", "ticket", "ticket", False, 0),
        ("F2-02", "扫地机能不能加个语音播报关闭功能", "ticket", "ticket", False, 0),
        ("F3-01", "客服态度太差了", "ticket", "ticket", False, 0),
        ("S16-05", "我能改收货地址吗？已经发货了", "rag", "kb_tool", True, 0),
        ("S14-01", "小米 14 Pro 保修期多久？", "rag", "kb", True, 0),
        ("S6-01", "小米 14 Pro 用什么充电器？", "rag", "kb", True, 0),
        ("C2-02", "苹果 15 Pro 怎么样？", "chitchat", "out_of_scope", False, 0),
    ],
)
def test_agent_intent_routing_acceptance_cases(
    case_id: str,
    message: str,
    route: str,
    system_route: str,
    requires_rag: bool,
    rag_match_count: int,
) -> None:
    agent, store = _agent()

    response = agent.handle_message(message, f"routing_{case_id}")
    tracker = store.retrieve(f"routing_{case_id}")
    metadata = response[0]["metadata"]

    assert tracker is not None
    assert metadata["route"] == route
    assert metadata["system_route"] == system_route
    assert metadata["requires_rag"] is requires_rag
    assert metadata["intentLeafIds"] == [INTENT_CASES[message].intent_id]
    assert metadata["intentSource"] == "llm_classifier"
    assert metadata["intentConfidence"] == 0.91
    assert metadata["rag_match_count"] == rag_match_count


def test_agent_f1_and_s16_do_not_start_order_id_flow() -> None:
    agent, store = _agent()

    agent.handle_message("我的扫地机充不进电了", "routing_f1_no_order")
    f1_tracker = store.retrieve("routing_f1_no_order")
    agent.handle_message("我能改收货地址吗？已经发货了", "routing_s16_no_order")
    s16_tracker = store.retrieve("routing_s16_no_order")

    assert f1_tracker is not None
    assert f1_tracker.active_flow is None
    assert f1_tracker.slot_to_collect is None
    assert s16_tracker is not None
    assert s16_tracker.active_flow is None
    assert s16_tracker.slot_to_collect is None
