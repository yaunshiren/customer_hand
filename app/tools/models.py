from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ToolStatus = Literal["success", "failed"]


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    """Stable response envelope for every business tool call."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1)
    success: bool
    status: ToolStatus
    arguments: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    latency_ms: int = Field(ge=0)
    trace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
