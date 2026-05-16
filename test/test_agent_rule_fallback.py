from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.agent import Agent  # noqa: E402
from app.core.tracker_store import InMemoryTrackerStore  # noqa: E402


def build_agent_with_llm_disabled() -> tuple[Agent, InMemoryTrackerStore]:
    store = InMemoryTrackerStore()
    agent = Agent(tracker_store=store, flows={})
    agent.llm_generator.client.enabled = False
    return agent, store


def test_rule_fallback_postsale_when_llm_disabled() -> None:
    agent, store = build_agent_with_llm_disabled()

    response = agent.handle_message("我要退货", "rule_postsale_user")
    tracker = store.retrieve("rule_postsale_user")

    assert tracker is not None
    assert tracker.active_flow == "postsale"
    assert "订单号" in response[0]["text"]
    assert tracker.get("latest_action_name") == "action_ask_order_id"


def test_rule_fallback_logistics_when_llm_disabled() -> None:
    agent, store = build_agent_with_llm_disabled()

    response = agent.handle_message("查物流", "rule_logistics_user")
    tracker = store.retrieve("rule_logistics_user")

    assert tracker is not None
    assert tracker.active_flow == "logistics"
    assert "订单号" in response[0]["text"]
    assert tracker.get("latest_action_name") == "action_ask_order_id"
