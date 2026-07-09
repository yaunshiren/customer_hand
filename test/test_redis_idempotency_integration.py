from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from app.entry.idempotency_store import IdempotencyScope, RedisIdempotencyStore


pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_REDIS_INTEGRATION", "").strip() != "1",
    reason="set RUN_REDIS_INTEGRATION=1 to run against a real Redis service",
)
def test_real_redis_atomic_first_seen_complete_and_replay() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    async def run() -> None:
        store = RedisIdempotencyStore(redis_url, ttl_seconds=30)
        scope = IdempotencyScope(
            tenant_id="integration-tenant",
            principal_id="integration-principal",
            scenario="ticket",
            capability="tool",
            idempotency_key=f"integration-{uuid4().hex}",
        )
        request_hash = uuid4().hex
        reservation_id = ""
        try:
            first_status, first = await store.begin(scope, request_hash)
            reservation_id = first.reservation_id
            await store.complete(
                scope,
                request_hash,
                reservation_id,
                {"ok": True},
            )
            replay_status, replay = await store.begin(scope, request_hash)

            assert first_status == "first_seen"
            assert replay_status == "replay"
            assert replay.response_snapshot == {"ok": True}
        finally:
            if reservation_id:
                await store.forget(scope, request_hash, reservation_id)
            await store.aclose()

    asyncio.run(run())
