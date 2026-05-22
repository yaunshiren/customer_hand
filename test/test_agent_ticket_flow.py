from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.agent import Agent
from app.core.tracker_store import InMemoryTrackerStore
from app.tickets.service import TicketService


class FakeTicketService(TicketService):
    def __init__(self) -> None:
        super().__init__()
        self.created_payloads: list[dict[str, Any]] = []

    def create_ticket(
        self,
        sender_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        ticket = super().create_ticket(sender_id=sender_id, text=text, metadata=metadata, **kwargs)
        self.created_payloads.append(
            {"sender_id": sender_id, "text": text, "metadata": metadata, "kwargs": kwargs, "ticket": ticket}
        )
        return ticket


def test_agent_routes_ticket_command_to_ticket_service() -> None:
    agent = Agent(tracker_store=InMemoryTrackerStore())
    fake_ticket_service = FakeTicketService()
    agent.ticket_service = fake_ticket_service

    def fake_try_llm_commands(tracker: Any, text: str) -> dict[str, Any]:
        return {
            "handled": True,
            "reply_text": None,
            "results": [
                {
                    "type": "ticket",
                    "success": True,
                    "data": {
                        "text": text,
                        "reason": "need_human",
                        "category": "complaint",
                        "priority": "high",
                    },
                }
            ],
        }

    agent._try_llm_commands = fake_try_llm_commands  # type: ignore[method-assign]

    response = agent.handle_message(message="我要人工处理", sender_id="ticket_sender_1")

    assert len(response) == 1
    assert response[0]["metadata"]["source"] == "ticket"
    assert response[0]["metadata"]["ticket_id"]
    assert response[0]["metadata"]["category"] == "complaint"
    assert response[0]["metadata"]["priority"] == "high"
    assert fake_ticket_service.created_payloads
    assert fake_ticket_service.created_payloads[0]["sender_id"] == "ticket_sender_1"
