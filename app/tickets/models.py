from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Ticket(BaseModel):
    ticket_id: str = Field(..., min_length=1)
    ticket_no: str | None = Field(default=None, min_length=1)
    sender_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    priority: str = Field(..., min_length=1)
    suggestion: str | None = None
    status: str = Field(default="open", min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TicketEvent(BaseModel):
    event_type: str = Field(..., min_length=1)
    from_status: str | None = None
    to_status: str | None = None
    actor: str = Field(default="system", min_length=1)
    trace_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
