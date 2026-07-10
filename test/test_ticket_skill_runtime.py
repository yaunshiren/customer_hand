from __future__ import annotations

import json
from typing import Any

from app.skills import SkillExecutionContext, skill_context_scope
from app.tickets.service import TicketNotFoundError, TicketService
from app.tickets.store import InMemoryTicketStore
from app.tools.service import MockBusinessToolService, ToolExecutionPolicy


def _context(*, idempotency_key: str | None = "idem-ticket-001") -> SkillExecutionContext:
    return SkillExecutionContext(
        principal_id="user_001",
        tenant_id="tenant_001",
        roles=frozenset({"user"}),
        source="api",
        scenario="tool",
        capability="ticket",
        trace_id="trace-ticket-skill",
        idempotency_key=idempotency_key,
        confirmed=False,
        legacy_compat=False,
    )


def test_create_ticket_uses_skill_runtime_and_preserves_business_result(monkeypatch) -> None:
    traces: list[dict[str, Any]] = []
    monkeypatch.setattr("app.tools.service.record_tool_trace", lambda **kwargs: traces.append(kwargs))
    service = MockBusinessToolService(
        ticket_service=TicketService(store=InMemoryTicketStore())
    )

    with skill_context_scope(_context()):
        result = service.create_ticket(
            "complaint",
            "Contact jane@example.com or 13800138000",
            "user_001",
        )

    assert result.success is True
    assert result.data is not None
    assert result.data["ticket_id"]
    assert result.data["ticket_no"].startswith("TKT-")
    assert result.data["description"] == "Contact jane@example.com or 13800138000"
    assert result.data["status"] == "open"
    assert result.metadata["runtime"] == "skill_runtime"
    assert result.metadata["legacy_compat"] is False
    assert result.metadata["max_retries"] == 0
    assert len(traces) == 1
    persisted = json.dumps(traces, ensure_ascii=False)
    assert "jane@example.com" not in persisted
    assert "13800138000" not in persisted
    assert result.data["ticket_id"] not in persisted
    assert result.data["ticket_no"] not in persisted


def test_create_ticket_requires_idempotency_without_calling_service() -> None:
    class CountingTicketService(TicketService):
        def __init__(self) -> None:
            super().__init__(store=InMemoryTicketStore())
            self.calls = 0

        def create_ticket(self, *args: Any, **kwargs: Any):
            self.calls += 1
            return super().create_ticket(*args, **kwargs)

    ticket_service = CountingTicketService()
    service = MockBusinessToolService(ticket_service=ticket_service)

    with skill_context_scope(_context(idempotency_key=None)):
        result = service.create_ticket("complaint", "need help", "user_001")

    assert result.success is False
    assert result.error and result.error.code == "SKILL_IDEMPOTENCY_REQUIRED"
    assert ticket_service.calls == 0


def test_create_ticket_failure_is_never_retried() -> None:
    class FailingTicketService(TicketService):
        def __init__(self) -> None:
            super().__init__(store=InMemoryTicketStore())
            self.calls = 0

        def create_ticket(self, *args: Any, **kwargs: Any):
            self.calls += 1
            raise ConnectionError("database unavailable")

    ticket_service = FailingTicketService()
    service = MockBusinessToolService(
        ticket_service=ticket_service,
        policy=ToolExecutionPolicy(max_retries=5),
    )

    with skill_context_scope(_context()):
        result = service.create_ticket("complaint", "need help", "user_001")

    assert result.success is False
    assert result.error and result.error.code == "SKILL_EXECUTION_FAILED"
    assert ticket_service.calls == 1
    assert result.metadata["max_retries"] == 0


def test_query_ticket_status_retries_transient_failure_once() -> None:
    store = InMemoryTicketStore()
    base_service = TicketService(store=store)
    ticket = base_service.create_ticket("user_001", "need help", category="complaint")

    class FlakyTicketService(TicketService):
        def __init__(self) -> None:
            super().__init__(store=store)
            self.calls = 0

        def query_ticket_status(self, ticket_no: str):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("temporary")
            return super().query_ticket_status(ticket_no)

    ticket_service = FlakyTicketService()
    service = MockBusinessToolService(
        ticket_service=ticket_service,
        policy=ToolExecutionPolicy(max_retries=1),
    )

    with skill_context_scope(_context(idempotency_key=None)):
        result = service.query_ticket_status(str(ticket.ticket_no))

    assert result.success is True
    assert result.data and result.data["ticket_id"] == ticket.ticket_id
    assert ticket_service.calls == 2
    assert result.metadata["attempt_count"] == 2


def test_query_ticket_not_found_is_not_retried() -> None:
    class MissingTicketService(TicketService):
        def __init__(self) -> None:
            super().__init__(store=InMemoryTicketStore())
            self.calls = 0

        def query_ticket_status(self, ticket_no: str):
            self.calls += 1
            raise TicketNotFoundError(ticket_no)

    ticket_service = MissingTicketService()
    service = MockBusinessToolService(
        ticket_service=ticket_service,
        policy=ToolExecutionPolicy(max_retries=4),
    )

    with skill_context_scope(_context(idempotency_key=None)):
        result = service.query_ticket_status("TKT-20260710-AAAAAAAAAAAA")

    assert result.success is False
    assert result.error and result.error.code == "TICKET_NOT_FOUND"
    assert ticket_service.calls == 1


def test_direct_legacy_tool_call_is_marked_compatibility_mode() -> None:
    service = MockBusinessToolService(
        ticket_service=TicketService(store=InMemoryTicketStore())
    )

    result = service.create_ticket("complaint", "legacy fixture", "legacy_user")

    assert result.success is True
    assert result.metadata["legacy_compat"] is True
    assert result.metadata["governance_bypassed"] is True

