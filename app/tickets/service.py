from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.core.trace import get_trace_id
from app.settings import settings

from .models import Ticket, TicketEvent
from .router import HumanHandoffDecision, should_handoff_to_human
from .store import InMemoryTicketStore, TicketStore
from .summary import SummaryResult, build_ticket_summary


class TicketNotFoundError(LookupError):
    def __init__(self, ticket_no: str) -> None:
        super().__init__(f"ticket not found: {ticket_no}")
        self.ticket_no = ticket_no


@dataclass
class TicketService:
    """Ticket domain service; persistence is hidden behind TicketStore."""

    store: TicketStore | None = None

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
        clean_sender_id = _required_text("sender_id", sender_id)
        clean_text = _required_text("text", text)
        summary_result = build_ticket_summary(clean_text)
        handoff_decision = should_handoff_to_human(clean_text)
        resolved_category = _optional_text(category) or summary_result.category
        resolved_priority = (
            _optional_text(priority)
            or ("high" if resolved_category == "complaint" else summary_result.priority)
        )
        should_handoff = handoff_decision.should_handoff or resolved_category == "complaint"
        now = datetime.utcnow()
        ticket_id = str(uuid4())
        ticket_no = _new_ticket_no(now)
        status = "open" if should_handoff else "resolved"

        ticket = Ticket(
            ticket_id=ticket_id,
            ticket_no=ticket_no,
            sender_id=clean_sender_id,
            title=_optional_text(title) or summary_result.title,
            summary=_optional_text(summary) or summary_result.summary,
            category=resolved_category,
            priority=resolved_priority,
            suggestion=_optional_text(suggestion) or summary_result.suggestion,
            status=status,
            created_at=now,
            updated_at=now,
            metadata={
                "raw_text": clean_text,
                "handoff": should_handoff,
                "handoff_reason": (
                    "投诉工单需要人工处理"
                    if resolved_category == "complaint" and not handoff_decision.should_handoff
                    else handoff_decision.reason
                ),
                **(metadata or {}),
            },
        )
        trace_id = get_trace_id()
        event = TicketEvent(
            event_type="created",
            from_status=None,
            to_status=status,
            actor="system",
            trace_id=trace_id if trace_id and trace_id != "-" else None,
            payload={
                "ticket_id": ticket_id,
                "ticket_no": ticket_no,
                "category": ticket.category,
                "priority": ticket.priority,
            },
            created_at=now,
        )
        return self._store().create_ticket(ticket, event)

    def query_ticket_status(self, ticket_no: str) -> Ticket:
        clean_ticket_no = _required_text("ticket_no", ticket_no).upper()
        ticket = self._store().get_ticket_by_no(clean_ticket_no)
        if ticket is None:
            raise TicketNotFoundError(clean_ticket_no)
        return ticket

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        return self._store().get_ticket(_required_text("ticket_id", ticket_id))

    def list_tickets_by_sender(self, sender_id: str) -> list[Ticket]:
        return self._store().list_tickets_by_sender(_required_text("sender_id", sender_id))

    def list_events(self, ticket_id: str) -> list[TicketEvent]:
        return self._store().list_events(_required_text("ticket_id", ticket_id))

    def should_handoff(
        self,
        text: str,
        confidence: float | None = None,
        unresolved_turns: int = 0,
    ) -> HumanHandoffDecision:
        return should_handoff_to_human(
            text,
            confidence=confidence,
            unresolved_turns=unresolved_turns,
        )

    def summarize(self, text: str) -> SummaryResult:
        return build_ticket_summary(text)

    def _store(self) -> TicketStore:
        if self.store is not None:
            return self.store
        if settings.ticket_store_backend == "memory":
            self.store = InMemoryTicketStore()
        elif settings.ticket_store_backend == "mysql":
            from app.persistence.ticket_repository import TicketRepository

            self.store = TicketRepository()
        else:  # pragma: no cover - Settings validates the literal.
            raise RuntimeError(f"unsupported ticket store backend: {settings.ticket_store_backend}")
        return self.store


def _new_ticket_no(now: datetime) -> str:
    return f"TKT-{now:%Y%m%d}-{uuid4().hex[:12].upper()}"


def _required_text(name: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
