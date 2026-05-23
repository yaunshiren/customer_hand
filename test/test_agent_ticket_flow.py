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
    def create_ticket(
        self,
        sender_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        return super().create_ticket(sender_id=sender_id, text=text, metadata=metadata, **kwargs)


class FakeLLMGenerator:
    enabled = True

    def generate(self, tracker: Any, text: str, flow_ids: list[str] | None = None) -> dict[str, Any]:
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


def test_agent_routes_ticket_command_to_ticket_service() -> None:
    agent = Agent(tracker_store=InMemoryTrackerStore())
    agent.ticket_service = FakeTicketService()
    agent.llm_generator = FakeLLMGenerator()

    response = agent.handle_message(message="我要人工处理", sender_id="ticket_sender_1")

    assert len(response) == 1
    assert "人工" in response[0]["text"] or response[0]["text"]
