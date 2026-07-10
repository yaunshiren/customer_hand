from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import OperationalError

from app.tickets.models import Ticket
from app.tickets.service import TicketNotFoundError, TicketService

from .models import (
    RetryPolicy,
    SkillDefinition,
    SkillExecutionContext,
    SkillHandlerError,
)
from .registry import SkillRegistry


class CreateTicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    user_id: str = Field(min_length=1)

    @field_validator("category", "description", "user_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} is required")
        return text


class QueryTicketStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_no: str = Field(min_length=1)

    @field_validator("ticket_no")
    @classmethod
    def _validate_ticket_no(cls, value: str) -> str:
        text = str(value or "").strip().upper()
        if not text:
            raise ValueError("ticket_no is required")
        return text


class TicketSkillOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str = Field(min_length=1)
    ticket_no: str = Field(min_length=1)
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    priority: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)


def build_default_registry(
    *,
    ticket_service: TicketService | None = None,
    timeout_ms: int = 3000,
    query_max_attempts: int = 2,
) -> SkillRegistry:
    service = ticket_service or TicketService()
    registry = SkillRegistry()

    def create_ticket_handler(
        payload: BaseModel,
        context: SkillExecutionContext,
    ) -> TicketSkillOutput:
        data = CreateTicketInput.model_validate(payload)
        ticket = service.create_ticket(
            sender_id=data.user_id,
            text=data.description,
            category=data.category,
            metadata={"source": "business_tool"},
        )
        return _ticket_output(ticket)

    def query_ticket_status_handler(
        payload: BaseModel,
        context: SkillExecutionContext,
    ) -> TicketSkillOutput:
        data = QueryTicketStatusInput.model_validate(payload)
        try:
            ticket = service.query_ticket_status(data.ticket_no)
        except TicketNotFoundError as exc:
            raise SkillHandlerError(
                "TICKET_NOT_FOUND",
                "Ticket does not exist.",
                retryable=False,
                details={"ticket_no": exc.ticket_no},
            ) from exc
        return _ticket_output(ticket)

    registry.register(
        SkillDefinition(
            name="create_ticket",
            description="Create a customer-service ticket that requires durable follow-up.",
            input_schema=CreateTicketInput,
            output_schema=TicketSkillOutput,
            risk_level="medium",
            required_roles=frozenset({"user", "evaluator", "admin"}),
            requires_confirmation=False,
            requires_idempotency=True,
            timeout_ms=max(1, int(timeout_ms)),
            retry_policy=RetryPolicy(max_attempts=1),
            handler=create_ticket_handler,
        )
    )
    registry.register(
        SkillDefinition(
            name="query_ticket_status",
            description="Query a persisted ticket by its user-visible ticket number.",
            input_schema=QueryTicketStatusInput,
            output_schema=TicketSkillOutput,
            risk_level="low",
            required_roles=frozenset({"user", "evaluator", "admin"}),
            requires_confirmation=False,
            requires_idempotency=False,
            timeout_ms=max(1, int(timeout_ms)),
            retry_policy=RetryPolicy(
                max_attempts=max(1, int(query_max_attempts)),
                retry_on_timeout=True,
                retryable_exceptions=(ConnectionError, TimeoutError, OperationalError),
            ),
            handler=query_ticket_status_handler,
        )
    )
    return registry


def _ticket_output(ticket: Ticket) -> TicketSkillOutput:
    return TicketSkillOutput(
        ticket_id=ticket.ticket_id,
        ticket_no=str(ticket.ticket_no or ""),
        category=ticket.category,
        description=str(ticket.metadata.get("raw_text") or ticket.summary),
        user_id=ticket.sender_id,
        status=ticket.status,
        priority=ticket.priority,
        created_at=ticket.created_at.isoformat(),
        updated_at=ticket.updated_at.isoformat(),
    )
