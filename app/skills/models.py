from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field


RiskLevel = Literal["low", "medium", "high"]
SkillStatus = Literal["success", "failed"]
SkillHandler = Callable[[BaseModel, "SkillExecutionContext"], Any]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_ms: int = 0
    retry_on_timeout: bool = False
    retryable_exceptions: tuple[type[BaseException], ...] = ()

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.backoff_ms < 0:
            raise ValueError("backoff_ms must not be negative")


@dataclass(frozen=True, slots=True)
class SkillExecutionContext:
    principal_id: str = "internal"
    tenant_id: str = "internal"
    roles: frozenset[str] = field(default_factory=frozenset)
    source: str = "internal"
    scenario: str = "tool"
    capability: str = "tool"
    trace_id: str | None = None
    idempotency_key: str | None = None
    confirmed: bool = False
    legacy_compat: bool = False


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    risk_level: RiskLevel
    required_roles: frozenset[str]
    requires_confirmation: bool
    requires_idempotency: bool
    timeout_ms: int
    retry_policy: RetryPolicy
    handler: SkillHandler

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("skill name must not be empty")
        if not self.description.strip():
            raise ValueError("skill description must not be empty")
        if self.timeout_ms < 1:
            raise ValueError("timeout_ms must be at least 1")
        if self.risk_level == "high" and not self.requires_confirmation:
            raise ValueError("high-risk skills must require confirmation")


class SkillError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class SkillExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(min_length=1)
    success: bool
    status: SkillStatus
    arguments: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] | None = None
    error: SkillError | None = None
    latency_ms: int = Field(ge=0)
    trace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillHandlerError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = dict(details or {})
