from __future__ import annotations

import json
import time
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.skills import (
    RetryPolicy,
    SkillDefinition,
    SkillExecutionContext,
    SkillExecutor,
    SkillRegistry,
    build_default_registry,
    current_skill_context,
    legacy_compat_context,
    skill_context_scope,
)


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1)


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1)


def _context(**overrides: Any) -> SkillExecutionContext:
    values: dict[str, Any] = {
        "principal_id": "principal_001",
        "tenant_id": "tenant_001",
        "roles": frozenset({"user"}),
        "source": "api",
        "scenario": "tool",
        "capability": "ticket",
        "trace_id": "trace-skill-001",
        "idempotency_key": "idem-001",
        "confirmed": True,
        "legacy_compat": False,
    }
    values.update(overrides)
    return SkillExecutionContext(**values)


def _definition(
    handler: Any,
    *,
    name: str = "echo",
    required_roles: frozenset[str] = frozenset({"user"}),
    requires_confirmation: bool = False,
    requires_idempotency: bool = False,
    timeout_ms: int = 100,
    retry_policy: RetryPolicy | None = None,
) -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description="Echo validated input.",
        input_schema=EchoInput,
        output_schema=EchoOutput,
        risk_level="medium" if requires_confirmation else "low",
        required_roles=required_roles,
        requires_confirmation=requires_confirmation,
        requires_idempotency=requires_idempotency,
        timeout_ms=timeout_ms,
        retry_policy=retry_policy or RetryPolicy(),
        handler=handler,
    )


def _executor(definition: SkillDefinition, traces: list[dict[str, Any]] | None = None) -> SkillExecutor:
    registry = SkillRegistry()
    registry.register(definition)
    return SkillExecutor(
        registry,
        trace_recorder=(lambda **kwargs: traces.append(kwargs)) if traces is not None else lambda **_: None,
    )


def test_registry_is_instance_local_and_default_builder_is_repeatable() -> None:
    handler = lambda payload, context: {"value": payload.value}
    first = SkillRegistry()
    second = SkillRegistry()
    definition = _definition(handler)

    first.register(definition)

    assert len(first) == 1
    assert len(second) == 0
    assert first.get("echo") is definition
    with pytest.raises(ValueError, match="already registered"):
        first.register(definition)

    default_one = build_default_registry()
    default_two = build_default_registry()
    assert [item.name for item in default_one.list()] == ["create_ticket", "query_ticket_status"]
    assert [item.name for item in default_two.list()] == ["create_ticket", "query_ticket_status"]
    assert default_one is not default_two


def test_executor_returns_standard_governance_and_validation_errors() -> None:
    executor = _executor(
        _definition(
            lambda payload, context: {"value": payload.value},
            requires_confirmation=True,
            requires_idempotency=True,
        )
    )

    invalid = executor.execute("echo", {"value": ""}, context=_context())
    denied = executor.execute("echo", {"value": "ok"}, context=_context(roles=frozenset({"guest"})))
    unconfirmed = executor.execute("echo", {"value": "ok"}, context=_context(confirmed=False))
    no_idempotency = executor.execute("echo", {"value": "ok"}, context=_context(idempotency_key=None))
    missing = executor.execute("missing", {}, context=_context())

    assert invalid.error and invalid.error.code == "SKILL_INPUT_INVALID"
    assert denied.error and denied.error.code == "SKILL_PERMISSION_DENIED"
    assert unconfirmed.error and unconfirmed.error.code == "SKILL_CONFIRMATION_REQUIRED"
    assert no_idempotency.error and no_idempotency.error.code == "SKILL_IDEMPOTENCY_REQUIRED"
    assert missing.error and missing.error.code == "SKILL_NOT_FOUND"


def test_executor_maps_timeout_output_and_raw_handler_failures() -> None:
    def slow(payload: EchoInput, context: SkillExecutionContext) -> dict[str, str]:
        time.sleep(0.03)
        return {"value": payload.value}

    timed_out = _executor(_definition(slow, timeout_ms=1)).execute(
        "echo", {"value": "ok"}, context=_context()
    )
    invalid_output = _executor(_definition(lambda payload, context: {})).execute(
        "echo", {"value": "ok"}, context=_context()
    )
    failed = _executor(
        _definition(lambda payload, context: (_ for _ in ()).throw(RuntimeError("database secret")))
    ).execute("echo", {"value": "ok"}, context=_context())

    assert timed_out.error and timed_out.error.code == "SKILL_TIMEOUT"
    assert timed_out.metadata["attempt_count"] == 1
    assert invalid_output.error and invalid_output.error.code == "SKILL_OUTPUT_INVALID"
    assert failed.error and failed.error.code == "SKILL_EXECUTION_FAILED"
    assert failed.error.message == "Skill execution failed."
    assert "database secret" not in failed.model_dump_json()


def test_executor_retries_only_configured_transient_exceptions() -> None:
    calls = 0

    def flaky(payload: EchoInput, context: SkillExecutionContext) -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("temporary")
        return {"value": payload.value}

    executor = _executor(
        _definition(
            flaky,
            retry_policy=RetryPolicy(max_attempts=2, retryable_exceptions=(ConnectionError,)),
        )
    )

    result = executor.execute("echo", {"value": "ok"}, context=_context())

    assert result.success is True
    assert calls == 2
    assert result.metadata["attempt_count"] == 2


def test_handler_worker_receives_context_and_scope_is_always_cleaned() -> None:
    observed: list[SkillExecutionContext | None] = []

    def handler(payload: EchoInput, context: SkillExecutionContext) -> dict[str, str]:
        observed.append(current_skill_context())
        return {"value": payload.value}

    context = _context(tenant_id="tenant-worker", principal_id="principal-worker")
    assert current_skill_context() is None
    result = _executor(_definition(handler)).execute("echo", {"value": "ok"}, context=context)

    assert result.success is True
    assert observed == [context]
    assert current_skill_context() is None

    with pytest.raises(RuntimeError):
        with skill_context_scope(context):
            assert current_skill_context() == context
            raise RuntimeError("force cleanup")
    assert current_skill_context() is None


def test_legacy_compat_is_explicit_and_trace_payload_is_redacted() -> None:
    traces: list[dict[str, Any]] = []
    executor = _executor(
        _definition(
            lambda payload, context: {"value": payload.value},
            requires_idempotency=True,
        ),
        traces,
    )
    sensitive = "demo-user-key jane@example.com 13800138000"

    result = executor.execute(
        "echo",
        {"value": sensitive},
        context=legacy_compat_context(trace_id="trace-legacy"),
    )

    assert result.success is True
    assert result.data == {"value": sensitive}
    assert result.metadata["legacy_compat"] is True
    assert result.metadata["governance_bypassed"] is True
    assert len(traces) == 1
    persisted = json.dumps(traces, ensure_ascii=False)
    assert "demo-user-key" not in persisted
    assert "jane@example.com" not in persisted
    assert "13800138000" not in persisted

