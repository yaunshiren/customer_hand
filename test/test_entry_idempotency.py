from __future__ import annotations

import asyncio

import pytest
from starlette.requests import Request

from app.core.exceptions import BadRequestError, ConflictError
from app.entry.idempotency import (
    IdempotencyStore,
    request_hash_for_task,
    run_with_idempotency,
)
from app.entry.idempotency_store import IdempotencyScope
from app.entry.models import EntryTask, Principal


def _request(path: str = "/api/messages") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": path,
            "root_path": "",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


def _task(
    *,
    text: str = "hello",
    key: str | None = "idem-1",
    scenario: str = "chat",
    capability: str | None = None,
) -> EntryTask:
    resolved_capability = capability or (
        "tool" if scenario in {"ticket", "invoice", "tool", "tool_write"} else "chat"
    )
    return EntryTask(
        trace_id="trace-1",
        request_id="req-1",
        source="api",
        scenario=scenario,
        capability=resolved_capability,
        principal=Principal(user_id="u1", tenant_id="tenant_a", roles=["user"], auth_type="dev_token"),
        sender_id="u1",
        conversation_id="c1",
        raw_text=text,
        normalized_text=text.strip(),
        idempotency_key=key,
    )


def test_idempotency_replays_same_key_and_hash() -> None:
    store = IdempotencyStore()
    calls = {"count": 0}

    async def handler() -> list[dict[str, object]]:
        calls["count"] += 1
        return [{"text": f"ok-{calls['count']}"}]

    first = asyncio.run(run_with_idempotency(_task(), _request(), handler, store=store))
    second = asyncio.run(run_with_idempotency(_task(), _request(), handler, store=store))

    assert first == [{"text": "ok-1"}]
    assert second == first
    assert calls["count"] == 1


def test_idempotency_same_key_different_hash_returns_conflict() -> None:
    store = IdempotencyStore()

    asyncio.run(run_with_idempotency(_task(text="hello"), _request(), lambda: {"ok": True}, store=store))

    with pytest.raises(ConflictError):
        asyncio.run(run_with_idempotency(_task(text="different"), _request(), lambda: {"ok": True}, store=store))


def test_same_hash_while_request_is_in_progress_has_distinct_error_code() -> None:
    store = IdempotencyStore()
    task = _task()
    request = _request()
    request_hash = request_hash_for_task(task, request)
    scope = IdempotencyScope(
        tenant_id=task.principal.tenant_id,
        principal_id=task.principal.principal_id,
        scenario=task.scenario,
        capability=task.capability,
        idempotency_key=task.idempotency_key or "",
    )
    asyncio.run(store.begin(scope, request_hash))

    with pytest.raises(ConflictError) as exc_info:
        asyncio.run(
            run_with_idempotency(
                task,
                request,
                lambda: {"should_not_run": True},
                store=store,
            )
        )

    assert exc_info.value.error_code == "idempotency_in_progress"


def test_request_hash_excludes_ephemeral_and_sensitive_fields() -> None:
    first = _task().model_copy(
        update={
            "trace_id": "trace-1",
            "request_id": "request-1",
            "metadata": {
                "trace_id": "metadata-trace-1",
                "timestamp": "2026-07-09T10:00:00Z",
                "authorization": "Bearer secret-a",
                "api_key": "secret-a",
                "business_flag": "stable",
            },
        }
    )
    second = first.model_copy(
        update={
            "trace_id": "trace-2",
            "request_id": "request-2",
            "metadata": {
                "trace_id": "metadata-trace-2",
                "timestamp": "2026-07-09T10:01:00Z",
                "authorization": "Bearer secret-b",
                "api_key": "secret-b",
                "business_flag": "stable",
            },
        }
    )

    assert request_hash_for_task(first, _request()) == request_hash_for_task(second, _request())
    assert request_hash_for_task(first, _request()) != request_hash_for_task(
        second.model_copy(update={"normalized_text": "different"}),
        _request(),
    )


@pytest.mark.parametrize(
    ("scenario", "capability"),
    [
        ("ticket", "tool"),
        ("invoice", "tool"),
        ("tool_write", "tool"),
        ("chat", "ticket"),
        ("chat", "invoice"),
        ("chat", "tool_write"),
        ("chat", "admin_reindex"),
    ],
)
def test_idempotency_required_for_high_risk_entry(
    scenario: str,
    capability: str,
) -> None:
    with pytest.raises(BadRequestError):
        asyncio.run(
            run_with_idempotency(
                _task(key=None, scenario=scenario, capability=capability),
                _request(),
                lambda: {"ok": True},
            )
        )


def test_normal_chat_text_does_not_require_idempotency_by_keyword() -> None:
    result = asyncio.run(
        run_with_idempotency(
            _task(
                text="What is the invoice policy?",
                key=None,
                scenario="chat",
                capability="chat",
            ),
            _request(),
            lambda: {"ok": True},
        )
    )

    assert result == {"ok": True}
