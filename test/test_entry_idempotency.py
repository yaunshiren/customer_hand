from __future__ import annotations

import asyncio

import pytest
from starlette.requests import Request

from app.core.exceptions import BadRequestError, ConflictError
from app.entry.idempotency import IdempotencyStore, run_with_idempotency
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


def _task(*, text: str = "hello", key: str | None = "idem-1", scenario: str = "chat") -> EntryTask:
    capability = "tool" if scenario in {"ticket", "invoice", "tool"} else "chat"
    return EntryTask(
        trace_id="trace-1",
        request_id="req-1",
        source="api",
        scenario=scenario,
        capability=capability,
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


def test_idempotency_required_for_ticket_scenario() -> None:
    with pytest.raises(BadRequestError):
        asyncio.run(run_with_idempotency(_task(key=None, scenario="ticket"), _request(), lambda: {"ok": True}))
