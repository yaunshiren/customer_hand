from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.entry.rate_limit_store import (
    RateLimitPolicy,
    RateLimitScope,
    RedisRateLimiter,
    build_rate_limit_key,
)


pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_REDIS_INTEGRATION", "").strip() != "1",
    reason="set RUN_REDIS_INTEGRATION=1 to run against a real Redis service",
)
def test_real_redis_atomic_token_bucket() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    async def run() -> None:
        limiter = RedisRateLimiter(redis_url)
        cleanup_client = Redis.from_url(redis_url, decode_responses=True)
        scope = RateLimitScope(
            tenant_id="integration-tenant",
            principal_scope=f"integration-{uuid4().hex}",
            source="api",
            scenario="chat",
            capability="chat",
        )
        policy = RateLimitPolicy(
            name="integration_chat",
            capacity=2,
            window_seconds=30,
        )
        key = build_rate_limit_key(scope, policy)
        try:
            first = await limiter.check(scope, policy)
            second = await limiter.check(scope, policy)
            limited = await limiter.check(scope, policy)

            assert first.allowed is True
            assert second.allowed is True
            assert limited.allowed is False
            assert limited.retry_after_seconds > 0
        finally:
            await cleanup_client.delete(key)
            await cleanup_client.aclose()
            await limiter.aclose()

    asyncio.run(run())
