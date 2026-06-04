from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.agent import Agent  # noqa: E402
from app.core.tracker_store import InMemoryTrackerStore  # noqa: E402
from app.rag.answerer import KnowledgeAnswerer  # noqa: E402


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


def _agent_with_llm_disabled() -> tuple[Agent, InMemoryTrackerStore]:
    store = InMemoryTrackerStore()
    agent = Agent(tracker_store=store, flows={})
    agent.llm_generator.client.enabled = False
    agent.knowledge_answerer = FakeKnowledgeAnswerer()
    return agent, store


def test_intent_policy_routes_feature_suggestion_to_ticket_without_rag() -> None:
    agent, _ = _agent_with_llm_disabled()

    response = agent.handle_message("希望 APP 能加个深色模式", "policy_feature_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "ticket"
    assert metadata["intentLeafIds"] == ["F2_功能建议"]
    assert metadata["intentSource"] == "rule_fallback"
    assert metadata["system_route"] == "ticket"
    assert metadata["requires_rag"] is False
    assert metadata["rag_match_count"] == 0


def test_intent_policy_routes_logistics_policy_to_rag_without_starting_flow() -> None:
    agent, store = _agent_with_llm_disabled()

    response = agent.handle_message("我能改收货地址吗？已经发货了", "policy_logistics_user")
    tracker = store.retrieve("policy_logistics_user")
    metadata = response[0]["metadata"]

    assert tracker is not None
    assert tracker.active_flow is None
    assert tracker.slot_to_collect is None
    assert metadata["route"] == "rag"
    assert metadata["intentLeafIds"] == ["S16_物流配送"]
    assert metadata["system_route"] == "kb_tool"
    assert metadata["requires_rag"] is True


def test_intent_policy_routes_fault_report_to_rag_without_order_slot() -> None:
    agent, store = _agent_with_llm_disabled()

    response = agent.handle_message("我的扫地机充不进电了", "policy_fault_user")
    tracker = store.retrieve("policy_fault_user")
    metadata = response[0]["metadata"]

    assert tracker is not None
    assert tracker.active_flow is None
    assert tracker.slot_to_collect is None
    assert metadata["route"] == "rag"
    assert metadata["intentLeafIds"] == ["F1_故障报告"]
    assert metadata["system_route"] == "kb_ticket"
    assert metadata["requires_rag"] is True
