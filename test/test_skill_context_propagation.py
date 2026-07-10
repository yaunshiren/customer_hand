from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from starlette.requests import Request

from app.entry.models import EntryTask, Principal
from app.services.message_service import run_agent
from app.skills import current_skill_context


def _task(suffix: str) -> EntryTask:
    return EntryTask(
        trace_id=f"trace-{suffix}",
        request_id=f"request-{suffix}",
        source="api",
        scenario="tool",
        capability="ticket",
        principal=Principal(
            principal_id=f"principal-{suffix}",
            tenant_id=f"tenant-{suffix}",
            roles=["user"],
            source="api_key",
            auth_type="api_key",
        ),
        sender_id=f"sender-{suffix}",
        conversation_id=f"conversation-{suffix}",
        raw_text="create ticket",
        normalized_text="create ticket",
        idempotency_key=f"idem-{suffix}",
    )


def _request(agent: Any, trace_id: str) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(agent=agent))
    request = Request({"type": "http", "method": "POST", "path": "/api/messages", "headers": [], "app": app})
    request.state.trace_id = trace_id
    return request


def test_message_worker_context_does_not_leak_between_concurrent_requests() -> None:
    observed: dict[str, tuple[str, str, str | None]] = {}

    class CapturingAgent:
        def handle_task(self, task: EntryTask) -> list[dict[str, object]]:
            context = current_skill_context()
            assert context is not None
            observed[task.request_id] = (
                context.principal_id,
                context.tenant_id,
                context.idempotency_key,
            )
            return []

    agent = CapturingAgent()
    first = _task("one")
    second = _task("two")

    async def run_both() -> None:
        await asyncio.gather(
            run_agent(first, _request(agent, first.trace_id)),
            run_agent(second, _request(agent, second.trace_id)),
        )

    asyncio.run(run_both())

    assert observed == {
        "request-one": ("principal-one", "tenant-one", "idem-one"),
        "request-two": ("principal-two", "tenant-two", "idem-two"),
    }
    assert current_skill_context() is None

