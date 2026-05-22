from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .models import Ticket
from .router import HumanHandoffDecision, should_handoff_to_human
from .store import InMemoryTicketStore
from .summary import SummaryResult, build_ticket_summary


@dataclass
class TicketService:
    store: InMemoryTicketStore = field(default_factory=InMemoryTicketStore)

    def create_ticket(
        self,
        sender_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        *,
        title: str | None = None,
        summary: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        suggestion: str | None = None,
    ) -> Ticket:
        summary_result = build_ticket_summary(text)
        handoff_decision = should_handoff_to_human(text)

        ticket = Ticket(
            ticket_id=str(uuid4()),
            sender_id=sender_id,
            title=title or summary_result.title,
            summary=summary or summary_result.summary,
            category=category or summary_result.category,
            priority=priority or summary_result.priority,
            suggestion=suggestion or summary_result.suggestion,
            status="open" if handoff_decision.should_handoff else "resolved",
            metadata={
                "raw_text": text,
                "handoff": handoff_decision.should_handoff,
                "handoff_reason": handoff_decision.reason,
                **(metadata or {}),
            },
        )
        return self.store.create_ticket(ticket)

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        return self.store.get_ticket(ticket_id)

    def list_tickets_by_sender(self, sender_id: str) -> list[Ticket]:
        return self.store.list_tickets_by_sender(sender_id)

    def should_handoff(self, text: str, confidence: float | None = None, unresolved_turns: int = 0) -> HumanHandoffDecision:
        return should_handoff_to_human(text, confidence=confidence, unresolved_turns=unresolved_turns)

    def summarize(self, text: str) -> SummaryResult:
        return build_ticket_summary(text)
