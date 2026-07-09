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
