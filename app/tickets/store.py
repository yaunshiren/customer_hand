from __future__ import annotations

from threading import Lock
from typing import Iterable, Protocol

from .models import Ticket, TicketEvent


class TicketStore(Protocol):
    def create_ticket(self, ticket: Ticket, event: TicketEvent | None = None) -> Ticket: ...

    def get_ticket(self, ticket_id: str) -> Ticket | None: ...

    def get_ticket_by_no(self, ticket_no: str) -> Ticket | None: ...

    def list_tickets_by_sender(self, sender_id: str) -> list[Ticket]: ...

    def list_all_tickets(self) -> list[Ticket]: ...

    def list_events(self, ticket_id: str) -> list[TicketEvent]: ...


class InMemoryTicketStore:
    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}
        self._ticket_nos: dict[str, str] = {}
        self._events: dict[str, list[TicketEvent]] = {}
        self._lock = Lock()

    def create_ticket(self, ticket: Ticket, event: TicketEvent | None = None) -> Ticket:
        with self._lock:
            self._tickets[ticket.ticket_id] = ticket
            if ticket.ticket_no:
                self._ticket_nos[ticket.ticket_no] = ticket.ticket_id
            if event is not None:
                self._events.setdefault(ticket.ticket_id, []).append(event)
        return ticket

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        with self._lock:
            return self._tickets.get(ticket_id)

    def get_ticket_by_no(self, ticket_no: str) -> Ticket | None:
        with self._lock:
            ticket_id = self._ticket_nos.get(ticket_no)
            return self._tickets.get(ticket_id) if ticket_id else None

    def list_tickets_by_sender(self, sender_id: str) -> list[Ticket]:
        with self._lock:
            return [ticket for ticket in self._tickets.values() if ticket.sender_id == sender_id]

    def list_all_tickets(self) -> list[Ticket]:
        with self._lock:
            return list(self._tickets.values())

    def delete_ticket(self, ticket_id: str) -> bool:
        with self._lock:
            ticket = self._tickets.pop(ticket_id, None)
            if ticket is None:
                return False
            if ticket.ticket_no:
                self._ticket_nos.pop(ticket.ticket_no, None)
            self._events.pop(ticket_id, None)
            return True

    def extend(self, tickets: Iterable[Ticket]) -> None:
        with self._lock:
            for ticket in tickets:
                self._tickets[ticket.ticket_id] = ticket
                if ticket.ticket_no:
                    self._ticket_nos[ticket.ticket_no] = ticket.ticket_id

    def list_events(self, ticket_id: str) -> list[TicketEvent]:
        with self._lock:
            return list(self._events.get(ticket_id, []))
