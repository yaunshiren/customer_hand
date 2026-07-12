from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.actions.base import Action, ActionResult  # noqa: E402
from app.actions.registry import clear_actions, register_action  # noqa: E402
from app.agent.graph import nodes  # noqa: E402
from app.core.trace import trace_scope  # noqa: E402
from app.core.tracker import DialogueStateTracker  # noqa: E402
from app.persistence.db import get_session_factory, ping_trace_db  # noqa: E402
from app.persistence.models import ToolTrace  # noqa: E402
from app.tickets.models import Ticket  # noqa: E402
from app.tickets.service import TicketService  # noqa: E402


@pytest.fixture(autouse=True)
def clean_action_registry() -> None:
    clear_actions()
    yield
    clear_actions()


@pytest.fixture()
def captured_tool_traces(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []

    def capture(**kwargs: Any) -> None:
        traces.append(kwargs)

    monkeypatch.setattr(nodes, "record_tool_trace", capture)
    return traces


def test_action_node_records_success_tool_trace(captured_tool_traces: list[dict[str, Any]]) -> None:
    tracker = DialogueStateTracker("tool_user_1")
    tracker.set_slot("order_id", "A12345678")

    result = nodes.action(
        {
            "tracker": tracker,
            "next_action": "action_show_logistics",
            "metadata": {"route": "flow"},
        }
    )

    assert result["action_result"]["metadata"]["action"] == "action_show_logistics"
    assert len(captured_tool_traces) == 1

    trace = captured_tool_traces[0]
    assert trace["tool_name"] == "action_show_logistics"
    assert trace["status"] == "success"
    assert isinstance(trace["latency_ms"], int)
    assert trace["arguments_json"]["action"] == "action_show_logistics"
    assert trace["arguments_json"]["tracker"]["slots"]["order_id"] == "A12345678"
    assert trace["result_json"]["metadata"]["order_id"] == "A12345678"
    assert trace["result_json"]["metadata"]["argument_status"] == "valid"


def test_action_node_records_failed_tool_trace(captured_tool_traces: list[dict[str, Any]]) -> None:
    class RaisingAction(Action):
        name = "action_boom"

        def run(self, tracker: DialogueStateTracker, **kwargs: Any) -> ActionResult:
            raise RuntimeError("boom")

    register_action(RaisingAction)

    result = nodes.action(
        {
            "tracker": DialogueStateTracker("tool_user_2"),
            "next_action": "action_boom",
            "metadata": {"route": "flow"},
        }
    )

    assert result["error"] == "boom"
    assert len(captured_tool_traces) == 1

    trace = captured_tool_traces[0]
    assert trace["tool_name"] == "action_boom"
    assert trace["status"] == "failed"
    assert trace["result_json"]["failure_type"] == "TOOL_FAILURE"
    assert trace["result_json"]["error_type"] == "RuntimeError"
    assert trace["result_json"]["metadata"]["error"] == "boom"


def test_ticket_node_records_success_tool_trace(captured_tool_traces: list[dict[str, Any]]) -> None:
    class FakeTicketService(TicketService):
        def create_ticket(self, **kwargs: Any) -> Ticket:
            return Ticket(
                ticket_id="ticket_001",
                sender_id=kwargs["sender_id"],
                title=kwargs["title"] or "Need human help",
                summary=kwargs["summary"] or "Customer needs human help",
                category=kwargs["category"] or "complaint",
                priority=kwargs["priority"] or "high",
                suggestion=kwargs["suggestion"],
                status="open",
                metadata={"source": "ticket", "raw_text": kwargs["text"]},
            )

    result = nodes.ticket(
        {
            "sender_id": "ticket_user_1",
            "message": "need human",
            "tracker": DialogueStateTracker("ticket_user_1"),
            "ticket_service": FakeTicketService(),
            "llm_results": [
                {
                    "type": "ticket",
                    "success": True,
                    "data": {
                        "text": "need human",
                        "title": "Human ticket",
                        "category": "complaint",
                        "priority": "high",
                    },
                }
            ],
        }
    )

    assert result["ticket"]["ticket_id"] == "ticket_001"
    assert len(captured_tool_traces) == 1

    trace = captured_tool_traces[0]
    assert trace["tool_name"] == "ticket_create"
    assert trace["status"] == "success"
    assert trace["arguments_json"]["sender_id"] == "ticket_user_1"
    assert trace["arguments_json"]["category"] == "complaint"
    assert trace["result_json"]["ticket_id"] == "ticket_001"
    assert trace["result_json"]["status"] == "open"


def test_ticket_node_records_failed_tool_trace(captured_tool_traces: list[dict[str, Any]]) -> None:
    class FailingTicketService(TicketService):
        def create_ticket(self, **kwargs: Any) -> Ticket:
            raise RuntimeError("ticket down")

    with pytest.raises(RuntimeError, match="ticket down"):
        nodes.ticket(
            {
                "sender_id": "ticket_user_2",
                "message": "need human",
                "ticket_service": FailingTicketService(),
                "llm_results": [{"type": "ticket", "success": True, "data": {"text": "need human"}}],
            }
        )

    assert len(captured_tool_traces) == 1

    trace = captured_tool_traces[0]
    assert trace["tool_name"] == "ticket_create"
    assert trace["status"] == "failed"
    assert trace["result_json"]["failure_type"] == "TOOL_FAILURE"
    assert trace["result_json"]["error_type"] == "RuntimeError"
    assert trace["result_json"]["error"] == "ticket down"


@pytest.mark.integration
@pytest.mark.mysql
def test_action_node_writes_tool_trace_to_mysql_when_available() -> None:
    try:
        ping_trace_db()
    except Exception as exc:  # pragma: no cover - depends on local MySQL.
        pytest.skip(f"trace database is not available: {exc}")

    trace_id = f"tool_trace_{uuid.uuid4().hex}"
    tracker = DialogueStateTracker("mysql_tool_user")
    tracker.set_slot("order_id", "A12345678")

    with trace_scope(trace_id):
        nodes.action({"tracker": tracker, "next_action": "action_show_logistics"})

    session = get_session_factory()()
    try:
        rows = list(session.execute(select(ToolTrace).where(ToolTrace.trace_id == trace_id)).scalars().all())
        assert len(rows) == 1
        assert rows[0].tool_name == "action_show_logistics"
        assert rows[0].status == "success"
        assert rows[0].arguments_json["tracker"]["slots"]["order_id"] == "A12345678"
        assert rows[0].result_json["metadata"]["argument_status"] == "valid"
    finally:
        session.execute(delete(ToolTrace).where(ToolTrace.trace_id == trace_id))
        session.commit()
        session.close()
