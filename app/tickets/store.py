from __future__ import annotations

from threading import Lock
from typing import Iterable

from .models import Ticket


class InMemoryTicketStore:
    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}
        self._lock = Lock()

    def create_ticket(self, ticket: Ticket) -> Ticket:
        with self._lock:
            self._tickets[ticket.ticket_id] = ticket
        return ticket

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        with self._lock:
            return self._tickets.get(ticket_id)

    def list_tickets_by_sender(self, sender_id: str) -> list[Ticket]:
        with self._lock:
            return [ticket for ticket in self._tickets.values() if ticket.sender_id == sender_id]

    def list_all_tickets(self) -> list[Ticket]:
        with self._lock:
            return list(self._tickets.values())

    def delete_ticket(self, ticket_id: str) -> bool:
        with self._lock:
            return self._tickets.pop(ticket_id, None) is not None

    def extend(self, tickets: Iterable[Ticket]) -> None:
        with self._lock:
            for ticket in tickets:
                self._tickets[ticket.ticket_id] = ticket
