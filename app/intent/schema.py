from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IntentType = Literal["KB", "TOOL", "KB_TOOL", "KB_TICKET", "TICKET", "FLOW", "CHITCHAT", "UNKNOWN"]
IntentSource = Literal["llm_classifier", "rule_fallback", "unknown"]
ExecutionRoute = Literal["rag", "tool", "ticket", "flow", "chitchat", "fallback"]


class IntentCandidate(BaseModel):
    intent_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class RoutePolicy(BaseModel):
    execution_route: ExecutionRoute
    system_route: str = Field(min_length=1)
    requires_rag: bool = False
    notes: str | None = None


class IntentDefinition(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: IntentType
    description: str = Field(min_length=1)
    examples: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    route_policy: RoutePolicy | None = None


class IntentResult(BaseModel):
    intent_id: str = Field(min_length=1)
    intent_name: str = Field(min_length=1)
    intent_type: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    candidates: list[IntentCandidate] = Field(default_factory=list)
    reason: str | None = None
    source: IntentSource = "unknown"
