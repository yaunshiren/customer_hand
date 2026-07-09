from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, select

from app.persistence.db import get_engine, ping_trace_db
from app.persistence.models import TicketEventRecord, TicketRecord
from app.persistence.ticket_repository import TicketRepository
from app.tickets.service import TicketService


@pytest.fixture()
def mysql_ticket_service() -> TicketService:
    try:
        ping_trace_db()
        inspector = inspect(get_engine())
        if not inspector.has_table("ticket") or not inspector.has_table("ticket_event"):
            pytest.skip("ticket tables are not migrated")
    except Exception as exc:  # pragma: no cover - depends on local MySQL.
        pytest.skip(f"trace database is not available: {exc}")

    repository = TicketRepository()
    service = TicketService(store=repository)
    created_ids: list[str] = []

    original_create = service.create_ticket

    def create_and_track(*args, **kwargs):
        ticket = original_create(*args, **kwargs)
        created_ids.append(ticket.ticket_id)
        return ticket

    service.create_ticket = create_and_track  # type: ignore[method-assign]
    try:
        yield service
    finally:
        for ticket_id in created_ids:
            repository.delete_ticket(ticket_id)


def test_mysql_create_persists_ticket_and_event(mysql_ticket_service: TicketService) -> None:
    created = mysql_ticket_service.create_ticket(
        sender_id=f"mysql-ticket-{uuid.uuid4().hex}",
        text="我要投诉客服态度差",
        category="complaint",
    )

    loaded = mysql_ticket_service.query_ticket_status(created.ticket_no or "")
    events = mysql_ticket_service.list_events(created.ticket_id)

    assert loaded.ticket_id == created.ticket_id
    assert loaded.ticket_no == created.ticket_no
    assert len(events) == 1
    assert events[0].event_type == "created"

    with get_engine().connect() as connection:
        ticket_pk = connection.execute(
            select(TicketRecord.id).where(TicketRecord.ticket_id == created.ticket_id)
        ).scalar_one()
        event_fk = connection.execute(
            select(TicketEventRecord.ticket_record_id).where(
                TicketEventRecord.ticket_record_id == ticket_pk
            )
        ).scalar_one()
    assert event_fk == ticket_pk
