from pathlib import Path

from app.agent.agent import Agent
from app.core.tracker_store import InMemoryTrackerStore
from app.core.flow_loader import FlowLoader
from app.settings import settings


def build_agent():
    store = InMemoryTrackerStore()
    flows = FlowLoader().load_directory(Path("data/flows"))
    return Agent(tracker_store=store, flows=flows, knowledge_dir=settings.knowledge_dir), store


def test_postsale_two_turns():
    agent, store = build_agent()

    r1 = agent.handle_message("我要退货", "u1")
    assert "请提供订单号" in r1[0]["text"]

    r2 = agent.handle_message("A12345678", "u1")
    assert "已收到订单号 A12345678" in r2[0]["text"]

    tracker = store.retrieve("u1")
    assert tracker["slots"]["order_id"] == "A12345678"
    assert tracker["active_flow"] is None


def test_logistics_two_turns():
    agent, store = build_agent()

    r1 = agent.handle_message("查物流", "u2")
    assert "请提供订单号" in r1[0]["text"]

    r2 = agent.handle_message("B88888888", "u2")
    assert "运输中" in r2[0]["text"]

    tracker = store.retrieve("u2")
    assert tracker["slots"]["order_id"] == "B88888888"
    assert tracker["active_flow"] is None
