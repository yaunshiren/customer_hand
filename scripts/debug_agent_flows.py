from pathlib import Path

from app.agent.agent import Agent
from app.core.tracker_store import InMemoryTrackerStore
from app.core.flow_loader import FlowLoader
from app.settings import settings
from app.entry.authorization import AuthorizedContext
from app.entry.models import Principal


def _principal(user_id: str) -> Principal:
    return Principal(
        user_id=user_id,
        tenant_id="local_debug",
        roles=["user"],
        source="debug_script",
        auth_type="system",
    )


def build_agent():
    store = InMemoryTrackerStore()
    flows = FlowLoader().load_directory(Path("data/flows"))
    return Agent(tracker_store=store, flows=flows, knowledge_dir=settings.knowledge_dir), store


def test_postsale_two_turns():
    agent, store = build_agent()

    principal = _principal("u1")
    r1 = agent.handle_message("我要退货", "u1", principal=principal)
    assert "请提供订单号" in r1[0]["text"]

    r2 = agent.handle_message("A12345678", "u1", principal=principal)
    assert "已收到订单号 A12345678" in r2[0]["text"]

    tracker = store.retrieve(AuthorizedContext.from_principal(principal))
    assert tracker["slots"]["order_id"] == "A12345678"
    assert tracker["active_flow"] is None


def test_logistics_two_turns():
    agent, store = build_agent()

    principal = _principal("u2")
    r1 = agent.handle_message("查物流", "u2", principal=principal)
    assert "请提供订单号" in r1[0]["text"]

    r2 = agent.handle_message("B88888888", "u2", principal=principal)
    assert "运输中" in r2[0]["text"]

    tracker = store.retrieve(AuthorizedContext.from_principal(principal))
    assert tracker["slots"]["order_id"] == "B88888888"
    assert tracker["active_flow"] is None
