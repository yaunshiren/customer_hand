from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.entry.models import EntryTask

from .models import SkillExecutionContext


_skill_context: ContextVar[SkillExecutionContext | None] = ContextVar(
    "skill_execution_context",
    default=None,
)


def context_from_entry_task(task: EntryTask) -> SkillExecutionContext:
    return SkillExecutionContext(
        principal_id=task.principal.principal_id,
        tenant_id=task.principal.tenant_id,
        roles=frozenset(str(role).strip().lower() for role in task.principal.roles if str(role).strip()),
        source=task.source,
        scenario=task.scenario,
        capability=task.capability,
        trace_id=task.trace_id,
        idempotency_key=task.idempotency_key,
        confirmed=False,
        legacy_compat=False,
    )


def legacy_compat_context(*, trace_id: str | None = None) -> SkillExecutionContext:
    """Trusted fallback for direct legacy tool calls outside the production API path."""

    return SkillExecutionContext(
        principal_id="legacy_tool_compat",
        tenant_id="legacy_tool_compat",
        roles=frozenset(),
        source="legacy_tool_compat",
        scenario="legacy_tool_compat",
        capability="tool",
        trace_id=trace_id,
        idempotency_key=None,
        confirmed=False,
        legacy_compat=True,
    )


def current_skill_context() -> SkillExecutionContext | None:
    return _skill_context.get()


@contextmanager
def skill_context_scope(context: SkillExecutionContext) -> Iterator[SkillExecutionContext]:
    token = _skill_context.set(context)
    try:
        yield context
    finally:
        _skill_context.reset(token)
