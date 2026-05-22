from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Ticket(BaseModel):
    ticket_id: str = Field(..., min_length=1)
    sender_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    priority: str = Field(..., min_length=1)
    suggestion: str | None = None
    status: str = Field(default="open", min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
