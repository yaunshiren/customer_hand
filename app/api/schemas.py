from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MessageRequest(BaseModel):
    sender_id: str | None = Field(default=None, min_length=1)
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    source: str = "api"
    scenario: str = "chat"
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageResponse(BaseModel):
    recipient_id: str
    text: str | None = None
    timestamp: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrackerResponse(BaseModel):
    sender_id: str
    exists: bool
    tracker: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    detail: str
    trace_id: str
    details: dict[str, Any] = Field(default_factory=dict)
