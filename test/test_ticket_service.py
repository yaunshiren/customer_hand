from __future__ import annotations

import re

import pytest

from app.tickets.service import TicketNotFoundError, TicketService
from app.tickets.store import InMemoryTicketStore


def test_create_ticket_generates_unique_ids_and_created_event() -> None:
    store = InMemoryTicketStore()
    service = TicketService(store=store)

    first = service.create_ticket(
        sender_id="user-1",
        text="我要投诉客服态度差",
        category="complaint",
    )
    second = service.create_ticket(
        sender_id="user-1",
        text="我要投诉物流一直没更新",
        category="complaint",
    )

    assert first.ticket_id != second.ticket_id
    assert first.ticket_no != second.ticket_no
    assert re.fullmatch(r"TKT-\d{8}-[A-F0-9]{12}", first.ticket_no or "")
    assert first.status == "open"
    events = service.list_events(first.ticket_id)
    assert len(events) == 1
    assert events[0].event_type == "created"
    assert events[0].to_status == "open"
    assert events[0].payload["ticket_no"] == first.ticket_no


def test_query_ticket_status_uses_user_visible_ticket_no() -> None:
    service = TicketService(store=InMemoryTicketStore())
    created = service.create_ticket(sender_id="user-2", text="我要人工处理")

    loaded = service.query_ticket_status(created.ticket_no or "")

    assert loaded.ticket_id == created.ticket_id
    assert loaded.ticket_no == created.ticket_no


def test_query_missing_ticket_raises_domain_error() -> None:
    service = TicketService(store=InMemoryTicketStore())

    with pytest.raises(TicketNotFoundError) as exc_info:
        service.query_ticket_status("TKT-20260709-FFFFFFFFFFFF")

    assert exc_info.value.ticket_no == "TKT-20260709-FFFFFFFFFFFF"


@pytest.mark.parametrize(
    ("sender_id", "text"),
    [
        ("", "valid issue"),
        ("user-1", ""),
        ("user-1", "   "),
    ],
)
def test_create_ticket_rejects_missing_required_fields(sender_id: str, text: str) -> None:
    service = TicketService(store=InMemoryTicketStore())

    with pytest.raises(ValueError):
        service.create_ticket(sender_id=sender_id, text=text)
