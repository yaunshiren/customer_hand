from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from starlette.requests import Request

from app.core.exceptions import IdempotencyBackendUnavailableError
from app.entry.idempotency import run_with_idempotency, safe_response_snapshot
from app.entry.idempotency_store import (
    IdempotencyScope,
    RedisIdempotencyStore,
    build_storage_key,
)
from app.entry.models import EntryTask, Principal
from app.tickets.service import TicketService
from app.tickets.store import InMemoryTicketStore


class FakeClock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeRedisClient:
    """Small EVAL-compatible fake; default tests never require a Redis process."""

    def __init__(self, clock: FakeClock, *, unavailable: bool = False) -> None:
        self.clock = clock
        self.unavailable = unavailable
        self.values: dict[str, tuple[str, float]] = {}
        self.close_calls = 0

    async def eval(self, script: str, numkeys: int, key: str, *args: str) -> Any:
        assert numkeys == 1
        if self.unavailable:
            raise ConnectionError("redis unavailable")
        self._expire(key)

        if "IDEMPOTENCY_BEGIN_V1" in script:
            request_hash, reservation_id, ttl_seconds = args
            created_at = self.clock()
            current = self._get(key)
            if current is None:
                record = {
                    "request_hash": request_hash,
                    "reservation_id": reservation_id,
                    "status": "in_progress",
                    "response_snapshot": None,
                    "created_at": created_at,
                    "expires_at": created_at + int(ttl_seconds),
                }
                encoded = _encoded(record)
                self.values[key] = (encoded, self.clock() + int(ttl_seconds))
                return ["first_seen", encoded]
            record = json.loads(current)
            if record["request_hash"] != request_hash:
                return ["conflict", current]
            if record["status"] == "completed":
                return ["replay", current]
            return ["in_progress", current]

        if "IDEMPOTENCY_COMPLETE_V1" in script:
            request_hash, reservation_id, encoded_snapshot = args
            current = self._get(key)
            if current is None:
                return ["missing", ""]
            record = json.loads(current)
            if (
                record["request_hash"] != request_hash
                or record["reservation_id"] != reservation_id
            ):
                return ["conflict", current]
            if record["status"] != "completed":
                record["status"] = "completed"
                record["response_snapshot"] = json.loads(encoded_snapshot)
                current = _encoded(record)
                _, expires_at = self.values[key]
                self.values[key] = (current, expires_at)
            return ["completed", current]

        if "IDEMPOTENCY_FORGET_V1" in script:
            request_hash, reservation_id = args
            current = self._get(key)
            if current is None:
                return 0
            record = json.loads(current)
            if (
                record["request_hash"] != request_hash
                or record["reservation_id"] != reservation_id
            ):
                return 0
            self.values.pop(key, None)
            return 1

        raise AssertionError("unknown script")

    async def aclose(self) -> None:
        self.close_calls += 1

    def raw_value(self, key: str) -> str | None:
        self._expire(key)
        return self._get(key)

    def _get(self, key: str) -> str | None:
        item = self.values.get(key)
        return item[0] if item is not None else None

    def _expire(self, key: str) -> None:
        item = self.values.get(key)
        if item is not None and item[1] <= self.clock():
            self.values.pop(key, None)


def _encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _scope(**overrides: str) -> IdempotencyScope:
    values = {
        "tenant_id": "tenant-a",
        "principal_id": "user-1",
        "scenario": "ticket",
        "capability": "tool",
        "idempotency_key": "idem-1",
        **overrides,
    }
    return IdempotencyScope(**values)


def _store(
    clock: FakeClock,
    *,
    ttl_seconds: int = 60,
    unavailable: bool = False,
) -> tuple[RedisIdempotencyStore, FakeRedisClient]:
    client = FakeRedisClient(clock, unavailable=unavailable)
    return (
        RedisIdempotencyStore(
            "redis://unused",
            ttl_seconds=ttl_seconds,
            client=client,
        ),
        client,
    )


def test_redis_store_first_seen_replay_and_conflict() -> None:
    clock = FakeClock()
    store, _ = _store(clock)

    first_status, first = asyncio.run(store.begin(_scope(), "hash-1"))
    asyncio.run(
        store.complete(
            _scope(),
            "hash-1",
            first.reservation_id,
            {"ticket_id": "ticket-1"},
        )
    )
    replay_status, replay = asyncio.run(store.begin(_scope(), "hash-1"))
    conflict_status, _ = asyncio.run(store.begin(_scope(), "hash-2"))

    assert first_status == "first_seen"
    assert replay_status == "replay"
    assert replay.response_snapshot == {"ticket_id": "ticket-1"}
    assert conflict_status == "conflict"


def test_redis_store_reports_same_hash_in_progress() -> None:
    clock = FakeClock()
    store, _ = _store(clock)

    first_status, _ = asyncio.run(store.begin(_scope(), "hash-1"))
    second_status, _ = asyncio.run(store.begin(_scope(), "hash-1"))

    assert first_status == "first_seen"
    assert second_status == "in_progress"


def test_redis_store_ttl_expiry_allows_first_seen_again() -> None:
    clock = FakeClock()
    store, _ = _store(clock, ttl_seconds=10)

    _, first = asyncio.run(store.begin(_scope(), "hash-1"))
    asyncio.run(store.complete(_scope(), "hash-1", first.reservation_id, {"ok": True}))
    clock.advance(11)
    status, record = asyncio.run(store.begin(_scope(), "hash-2"))

    assert status == "first_seen"
    assert record.request_hash == "hash-2"


def test_expired_reservation_cannot_delete_new_reservation() -> None:
    clock = FakeClock()
    store, _ = _store(clock, ttl_seconds=10)

    _, expired = asyncio.run(store.begin(_scope(), "hash-1"))
    clock.advance(11)
    _, current = asyncio.run(store.begin(_scope(), "hash-1"))
    asyncio.run(
        store.forget(
            _scope(),
            "hash-1",
            expired.reservation_id,
        )
    )
    status, preserved = asyncio.run(store.begin(_scope(), "hash-1"))

    assert expired.reservation_id != current.reservation_id
    assert status == "in_progress"
    assert preserved.reservation_id == current.reservation_id


def test_redis_store_unavailable_fails_closed() -> None:
    clock = FakeClock()
    store, _ = _store(clock, unavailable=True)

    with pytest.raises(IdempotencyBackendUnavailableError) as exc_info:
        asyncio.run(store.begin(_scope(), "hash-1"))

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "idempotency_backend_unavailable"
    assert "redis://unused" not in exc_info.value.message


def test_redis_key_hashes_identity_and_normalizes_untrusted_components() -> None:
    scope = _scope(
        tenant_id="tenant/private",
        principal_id="person@example.com",
        scenario="../../Ticket Status",
        capability="Tool Write\r\n",
        idempotency_key="customer-secret-key",
    )

    key = build_storage_key(scope)

    assert "tenant/private" not in key
    assert "person@example.com" not in key
    assert "customer-secret-key" not in key
    assert "\r" not in key and "\n" not in key and "/" not in key
    assert key.startswith("customer_hand:idempotency:v1:")


def test_redis_value_contains_only_sanitized_response_snapshot() -> None:
    clock = FakeClock()
    store, client = _store(clock)
    scope = _scope()
    unsafe_response = {
        "text": "创建投诉工单；联系 13812345678 或 alice@example.com，key=demo-user-key",
        "authorization": "Bearer demo-user-key",
        "raw_text": "完整原始请求",
        "metadata": {
            "memory_snapshot": {"messages": ["完整上下文"]},
            "status": "created",
        },
    }
    snapshot = safe_response_snapshot(
        unsafe_response,
        secrets=["demo-user-key", "创建投诉工单"],
    )

    _, first = asyncio.run(store.begin(scope, "hash-1"))
    asyncio.run(store.complete(scope, "hash-1", first.reservation_id, snapshot))
    raw = client.raw_value(build_storage_key(scope))

    assert raw is not None
    assert "demo-user-key" not in raw
    assert "13812345678" not in raw
    assert "alice@example.com" not in raw
    assert "创建投诉工单" not in raw
    assert "完整原始请求" not in raw
    assert "完整上下文" not in raw
    assert "request_hash" in raw
    assert "response_snapshot" in raw


def test_redis_close_is_repeatable() -> None:
    clock = FakeClock()
    store, client = _store(clock)

    asyncio.run(store.aclose())
    asyncio.run(store.aclose())

    assert client.close_calls == 1


def test_replayed_create_ticket_does_not_create_second_ticket() -> None:
    clock = FakeClock()
    idempotency_store, _ = _store(clock)
    ticket_store = InMemoryTicketStore()
    ticket_service = TicketService(store=ticket_store)
    calls = {"count": 0}
    task = EntryTask(
        trace_id="trace-1",
        request_id="request-1",
        source="api",
        scenario="ticket",
        capability="tool",
        principal=Principal(
            principal_id="user-1",
            tenant_id="tenant-a",
            roles=["user"],
            source="api_key",
            auth_type="api_key",
        ),
        sender_id="user-1",
        conversation_id="conversation-1",
        raw_text="创建投诉工单",
        normalized_text="创建投诉工单",
        idempotency_key="create-ticket-once",
    )

    def create_ticket() -> dict[str, Any]:
        calls["count"] += 1
        ticket = ticket_service.create_ticket(
            sender_id="user-1",
            text="创建投诉工单",
            category="complaint",
        )
        return {
            "ticket_id": ticket.ticket_id,
            "ticket_no": ticket.ticket_no,
            "status": ticket.status,
        }

    first = asyncio.run(
        run_with_idempotency(
            task,
            _request(),
            create_ticket,
            store=idempotency_store,
        )
    )
    replay = asyncio.run(
        run_with_idempotency(
            task.model_copy(update={"trace_id": "trace-2", "request_id": "request-2"}),
            _request(),
            create_ticket,
            store=idempotency_store,
        )
    )

    assert replay == first
    assert calls["count"] == 1
    assert len(ticket_store.list_all_tickets()) == 1
