from __future__ import annotations

import asyncio
import math
from dataclasses import replace
from typing import Any

import pytest

from app.core.exceptions import RateLimitBackendUnavailableError
from app.entry.rate_limit_store import (
    RateLimitPolicy,
    RateLimitScope,
    RedisRateLimiter,
    build_rate_limit_key,
)


class FakeClock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeRedisClient:
    """Small EVAL-compatible fake; default pytest never connects to Redis."""

    def __init__(self, clock: FakeClock, *, unavailable: bool = False) -> None:
        self.clock = clock
        self.unavailable = unavailable
        self.values: dict[str, dict[str, float]] = {}
        self.expires_at: dict[str, float] = {}
        self.close_calls = 0

    async def eval(self, script: str, numkeys: int, key: str, *args: str) -> Any:
        assert numkeys == 1
        assert "RATE_LIMIT_TOKEN_BUCKET_V1" in script
        if self.unavailable:
            raise ConnectionError("redis unavailable")

        capacity = int(args[0])
        window_seconds = int(args[1])
        now = self.clock()
        bucket = self.values.get(key)
        if bucket is not None and self.expires_at[key] <= now:
            bucket = None
            self.values.pop(key, None)
            self.expires_at.pop(key, None)

        tokens = float(capacity) if bucket is None else bucket["tokens"]
        updated_at = now if bucket is None else bucket["updated_at"]
        refill_rate = capacity / window_seconds
        elapsed = max(0.0, now - updated_at)
        tokens = min(float(capacity), tokens + elapsed * refill_rate)

        allowed = 0
        retry_after = 0
        if tokens >= 1.0:
            allowed = 1
            tokens -= 1.0
        else:
            retry_after = max(1, math.ceil((1.0 - tokens) / refill_rate))

        self.values[key] = {
            "tokens": tokens,
            "updated_at": now,
        }
        self.expires_at[key] = now + window_seconds
        return [allowed, str(tokens), retry_after]

    async def aclose(self) -> None:
        self.close_calls += 1

    def raw_value(self, key: str) -> dict[str, float] | None:
        return self.values.get(key)


def _policy(*, capacity: int = 2, window_seconds: int = 10) -> RateLimitPolicy:
    return RateLimitPolicy(
        name="chat_per_user",
        capacity=capacity,
        window_seconds=window_seconds,
    )


def _scope(**overrides: str) -> RateLimitScope:
    values = {
        "tenant_id": "tenant-a",
        "principal_scope": "user-1",
        "source": "api",
        "scenario": "chat",
        "capability": "chat",
        **overrides,
    }
    return RateLimitScope(**values)


def _limiter(
    clock: FakeClock,
    *,
    unavailable: bool = False,
) -> tuple[RedisRateLimiter, FakeRedisClient]:
    client = FakeRedisClient(clock, unavailable=unavailable)
    return RedisRateLimiter("redis://unused", client=client), client


def test_redis_rate_limiter_allows_until_threshold_then_limits() -> None:
    clock = FakeClock()
    limiter, _ = _limiter(clock)

    first = asyncio.run(limiter.check(_scope(), _policy()))
    second = asyncio.run(limiter.check(_scope(), _policy()))
    limited = asyncio.run(limiter.check(_scope(), _policy()))

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0
    assert limited.allowed is False
    assert limited.retry_after_seconds == 5


def test_redis_rate_limiter_retry_after_tracks_partial_refill() -> None:
    clock = FakeClock()
    limiter, _ = _limiter(clock)
    asyncio.run(limiter.check(_scope(), _policy()))
    asyncio.run(limiter.check(_scope(), _policy()))
    clock.advance(2)

    limited = asyncio.run(limiter.check(_scope(), _policy()))

    assert limited.allowed is False
    assert limited.retry_after_seconds == 3


def test_redis_rate_limiter_recovers_after_ttl_window() -> None:
    clock = FakeClock()
    limiter, _ = _limiter(clock)
    asyncio.run(limiter.check(_scope(), _policy()))
    asyncio.run(limiter.check(_scope(), _policy()))
    clock.advance(11)

    decision = asyncio.run(limiter.check(_scope(), _policy()))

    assert decision.allowed is True
    assert decision.remaining == 1


def test_rate_limit_dimensions_are_isolated() -> None:
    clock = FakeClock()
    limiter, _ = _limiter(clock)
    policy = _policy(capacity=1)
    base = _scope()
    scopes = [
        base,
        replace(base, tenant_id="tenant-b"),
        replace(base, principal_scope="user-2"),
        replace(base, source="webhook"),
        replace(base, scenario="ticket"),
        replace(base, capability="tool"),
    ]

    decisions = [asyncio.run(limiter.check(scope, policy)) for scope in scopes]

    assert all(decision.allowed for decision in decisions)
    assert len({decision.key for decision in decisions}) == len(scopes)
    assert asyncio.run(limiter.check(base, policy)).allowed is False


def test_redis_rate_limiter_unavailable_fails_closed() -> None:
    clock = FakeClock()
    limiter, _ = _limiter(clock, unavailable=True)

    with pytest.raises(RateLimitBackendUnavailableError) as exc_info:
        asyncio.run(limiter.check(_scope(), _policy()))

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "rate_limit_backend_unavailable"
    assert "redis://unused" not in exc_info.value.message


def test_redis_key_and_value_do_not_contain_sensitive_input() -> None:
    clock = FakeClock()
    limiter, client = _limiter(clock)
    scope = _scope(
        tenant_id="alice@example.com",
        principal_scope="13812345678",
        source="Bearer demo-user-key",
        scenario="customer raw message",
        capability="demo-user-key",
    )

    decision = asyncio.run(limiter.check(scope, _policy()))
    raw = client.raw_value(build_rate_limit_key(scope, _policy()))
    combined = f"{decision.key} {raw}"

    assert decision.key.startswith("customer_hand:rate_limit:v1:")
    assert "alice@example.com" not in combined
    assert "13812345678" not in combined
    assert "demo-user-key" not in combined
    assert "customer raw message" not in combined
    assert set(raw or {}) == {"tokens", "updated_at"}


def test_redis_rate_limiter_close_is_repeatable() -> None:
    clock = FakeClock()
    limiter, client = _limiter(clock)

    asyncio.run(limiter.aclose())
    asyncio.run(limiter.aclose())

    assert client.close_calls == 1
