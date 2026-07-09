from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence.db import get_session_factory
from app.persistence.models import TicketEventRecord, TicketRecord
from app.persistence.repositories import RepositoryError
from app.tickets.models import Ticket, TicketEvent


class TicketRepository:
    """MySQL-backed ticket persistence boundary."""

    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    def create_ticket(self, ticket: Ticket, event: TicketEvent | None = None) -> Ticket:
        ticket_no = _required_text("ticket_no", ticket.ticket_no, max_len=32)
        row = TicketRecord(
            ticket_id=_required_text("ticket_id", ticket.ticket_id, max_len=64),
            ticket_no=ticket_no,
            sender_id=_required_text("sender_id", ticket.sender_id, max_len=128),
            title=_required_text("title", ticket.title, max_len=255),
            summary=_required_text("summary", ticket.summary),
            category=_required_text("category", ticket.category, max_len=64),
            priority=_required_text("priority", ticket.priority, max_len=32),
            suggestion=_optional_text("suggestion", ticket.suggestion),
            status=_required_text("status", ticket.status, max_len=32),
            metadata_json=_json_dict(ticket.metadata),
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
        )

        session = self._session_factory()
        try:
            session.add(row)
            session.flush()
            if event is not None:
                session.add(_event_record(row.id, event))
            session.commit()
            session.refresh(row)
            return _ticket_from_record(row)
        except IntegrityError as exc:
            session.rollback()
            raise RepositoryError("ticket_id or ticket_no already exists") from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        key = _required_text("ticket_id", ticket_id, max_len=64)
        return self._one(select(TicketRecord).where(TicketRecord.ticket_id == key))

    def get_ticket_by_no(self, ticket_no: str) -> Ticket | None:
        key = _required_text("ticket_no", ticket_no, max_len=32)
        return self._one(select(TicketRecord).where(TicketRecord.ticket_no == key))

    def list_tickets_by_sender(self, sender_id: str) -> list[Ticket]:
        key = _required_text("sender_id", sender_id, max_len=128)
        session = self._session_factory()
        try:
            rows = session.execute(
                select(TicketRecord)
                .where(TicketRecord.sender_id == key)
                .order_by(TicketRecord.created_at.desc(), TicketRecord.id.desc())
            ).scalars()
            return [_ticket_from_record(row) for row in rows]
        finally:
            session.close()

    def list_all_tickets(self) -> list[Ticket]:
        session = self._session_factory()
        try:
            rows = session.execute(
                select(TicketRecord).order_by(TicketRecord.created_at.desc(), TicketRecord.id.desc())
            ).scalars()
            return [_ticket_from_record(row) for row in rows]
        finally:
            session.close()

    def list_events(self, ticket_id: str) -> list[TicketEvent]:
        key = _required_text("ticket_id", ticket_id, max_len=64)
        session = self._session_factory()
        try:
            rows = session.execute(
                select(TicketEventRecord)
                .join(TicketRecord, TicketEventRecord.ticket_record_id == TicketRecord.id)
                .where(TicketRecord.ticket_id == key)
                .order_by(TicketEventRecord.id.asc())
            ).scalars()
            return [_event_from_record(row) for row in rows]
        finally:
            session.close()

    def delete_ticket(self, ticket_id: str) -> bool:
        key = _required_text("ticket_id", ticket_id, max_len=64)
        session = self._session_factory()
        try:
            row = session.execute(
                select(TicketRecord).where(TicketRecord.ticket_id == key)
            ).scalar_one_or_none()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _one(self, statement: Any) -> Ticket | None:
        session = self._session_factory()
        try:
            row = session.execute(statement).scalar_one_or_none()
            return _ticket_from_record(row) if row is not None else None
        finally:
            session.close()


def _event_record(ticket_record_id: int, event: TicketEvent) -> TicketEventRecord:
    return TicketEventRecord(
        ticket_record_id=ticket_record_id,
        event_type=_required_text("event_type", event.event_type, max_len=64),
        from_status=_optional_text("from_status", event.from_status, max_len=32),
        to_status=_optional_text("to_status", event.to_status, max_len=32),
        actor=_required_text("actor", event.actor, max_len=64),
        trace_id=_optional_text("trace_id", event.trace_id, max_len=64),
        payload_json=_json_dict(event.payload),
        created_at=event.created_at,
    )


def _ticket_from_record(row: TicketRecord) -> Ticket:
    return Ticket(
        ticket_id=row.ticket_id,
        ticket_no=row.ticket_no,
        sender_id=row.sender_id,
        title=row.title,
        summary=row.summary,
        category=row.category,
        priority=row.priority,
        suggestion=row.suggestion,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=dict(row.metadata_json or {}),
    )


def _event_from_record(row: TicketEventRecord) -> TicketEvent:
    return TicketEvent(
        event_type=row.event_type,
        from_status=row.from_status,
        to_status=row.to_status,
        actor=row.actor,
        trace_id=row.trace_id,
        payload=dict(row.payload_json or {}),
        created_at=row.created_at,
    )


def _required_text(name: str, value: Any, *, max_len: int | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        raise RepositoryError(f"{name} is required")
    if max_len is not None and len(text) > max_len:
        raise RepositoryError(f"{name} exceeds max length {max_len}")
    return text


def _optional_text(name: str, value: Any, *, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if max_len is not None and len(text) > max_len:
        raise RepositoryError(f"{name} exceeds max length {max_len}")
    return text or None


def _json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RepositoryError("JSON payload must be an object")
    return dict(value)
