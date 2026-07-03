from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


EntrySource = Literal["web", "app", "api", "webhook", "scheduler"]
AuthType = Literal["anonymous", "dev_token", "jwt", "api_key", "system"]


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(default="anonymous", min_length=1)
    tenant_id: str = Field(default="default", min_length=1)
    roles: list[str] = Field(default_factory=lambda: ["anonymous"])
    data_scope: dict[str, Any] = Field(default_factory=dict)
    auth_type: AuthType = "anonymous"

    @field_validator("roles")
    @classmethod
    def _roles_not_empty(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned or ["anonymous"]


class SecurityFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    has_pii: bool = False
    prompt_injection_risk: bool = False
    malicious_input_risk: bool = False
    redacted_text: str | None = None
    reasons: list[str] = Field(default_factory=list)


class EntryTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    source: EntrySource = "api"
    scenario: str = Field(default="chat", min_length=1)
    capability: str = Field(default="chat", min_length=1)
    principal: Principal = Field(default_factory=Principal)
    sender_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    idempotency_key: str | None = None
    security_flags: SecurityFlags = Field(default_factory=SecurityFlags)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "trace_id",
        "request_id",
        "scenario",
        "capability",
        "sender_id",
        "conversation_id",
        "raw_text",
        "normalized_text",
        mode="before",
    )
    @classmethod
    def _strip_required_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("field must not be empty")
        return text