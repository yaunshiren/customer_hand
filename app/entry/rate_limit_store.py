from __future__ import annotations

import hashlib
import inspect
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.exceptions import RateLimitBackendUnavailableError


_SAFE_COMPONENT_RE = re.compile(r"[^a-z0-9_.-]+")
_SAFE_PREFIX_RE = re.compile(r"[^A-Za-z0-9:_.-]+")

_TOKEN_BUCKET_SCRIPT = """
-- RATE_LIMIT_TOKEN_BUCKET_V1
redis.replicate_commands()
local redis_time = redis.call("TIME")
local now = tonumber(redis_time[1]) + tonumber(redis_time[2]) / 1000000
local capacity = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local refill_rate = capacity / window_seconds

local tokens = tonumber(redis.call("HGET", KEYS[1], "tokens"))
local updated_at = tonumber(redis.call("HGET", KEYS[1], "updated_at"))
if not tokens or not updated_at then
    tokens = capacity
    updated_at = now
end

local elapsed = math.max(0, now - updated_at)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
local retry_after = 0
if tokens >= 1 then
    allowed = 1
    tokens = tokens - 1
else
    retry_after = math.max(1, math.ceil((1 - tokens) / refill_rate))
end

redis.call("HSET", KEYS[1], "tokens", tostring(tokens))
redis.call("HSET", KEYS[1], "updated_at", tostring(now))
redis.call("EXPIRE", KEYS[1], math.max(1, math.ceil(window_seconds)))
return {allowed, tostring(tokens), retry_after}
"""


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    capacity: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitScope:
    tenant_id: str
    principal_scope: str
    source: str
    scenario: str
    capability: str


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    key: str
    policy: RateLimitPolicy
    retry_after_seconds: int = 0
    remaining: int = 0


class RateLimiterProtocol(Protocol):
    async def check(
        self,
        scope: RateLimitScope,
        policy: RateLimitPolicy,
    ) -> RateLimitDecision: ...

    async def aclose(self) -> None: ...


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class InMemoryRateLimiter:
    """Local token bucket for tests and single-process demonstrations."""

    def __init__(
        self,
        *,
        key_prefix: str = "customer_hand:rate_limit:v1",
        time_fn: Any = time.monotonic,
    ) -> None:
        self.key_prefix = key_prefix
        self._time_fn = time_fn
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    async def check(
        self,
        scope: RateLimitScope,
        policy: RateLimitPolicy,
    ) -> RateLimitDecision:
        current = float(self._time_fn())
        key = build_rate_limit_key(scope, policy, prefix=self.key_prefix)
        refill_rate = policy.capacity / policy.window_seconds

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(policy.capacity), updated_at=current)

            elapsed = max(0.0, current - bucket.updated_at)
            tokens = min(float(policy.capacity), bucket.tokens + elapsed * refill_rate)

            if tokens >= 1.0:
                tokens -= 1.0
                self._buckets[key] = _Bucket(tokens=tokens, updated_at=current)
                return RateLimitDecision(
                    allowed=True,
                    key=key,
                    policy=policy,
                    remaining=max(0, int(math.floor(tokens))),
                )

            retry_after = max(1, math.ceil((1.0 - tokens) / refill_rate))
            self._buckets[key] = _Bucket(tokens=tokens, updated_at=current)
            return RateLimitDecision(
                allowed=False,
                key=key,
                policy=policy,
                retry_after_seconds=retry_after,
                remaining=0,
            )

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    async def aclose(self) -> None:
        return None


class RedisRateLimiter:
    """Distributed token bucket backed by an atomic Redis Lua script."""

    def __init__(
        self,
        redis_url: str,
        *,
        key_prefix: str = "customer_hand:rate_limit:v1",
        client: Any | None = None,
    ) -> None:
        self.key_prefix = key_prefix
        self._client = client or Redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self._closed = False

    async def check(
        self,
        scope: RateLimitScope,
        policy: RateLimitPolicy,
    ) -> RateLimitDecision:
        key = build_rate_limit_key(scope, policy, prefix=self.key_prefix)
        try:
            raw = await self._client.eval(
                _TOKEN_BUCKET_SCRIPT,
                1,
                key,
                str(policy.capacity),
                str(policy.window_seconds),
            )
            allowed, tokens, retry_after = _script_result(raw)
            return RateLimitDecision(
                allowed=allowed,
                key=key,
                policy=policy,
                retry_after_seconds=retry_after,
                remaining=max(0, int(math.floor(tokens))),
            )
        except (RedisError, OSError, TimeoutError, ValueError, TypeError) as exc:
            raise RateLimitBackendUnavailableError(
                "rate limit backend is unavailable"
            ) from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        closer = getattr(self._client, "aclose", None)
        if closer is None:
            closer = getattr(self._client, "close", None)
        if closer is None:
            return
        try:
            result = closer()
            if inspect.isawaitable(result):
                await result
        except (RedisError, OSError, TimeoutError):
            return


def build_rate_limit_key(
    scope: RateLimitScope,
    policy: RateLimitPolicy,
    *,
    prefix: str = "customer_hand:rate_limit:v1",
) -> str:
    safe_prefix = _SAFE_PREFIX_RE.sub("_", str(prefix or "").strip())[:100].strip(":._-")
    safe_prefix = safe_prefix or "customer_hand:rate_limit:v1"
    if not safe_prefix.lower().startswith("customer_hand:"):
        safe_prefix = f"customer_hand:{safe_prefix}"
    return ":".join(
        (
            safe_prefix,
            normalize_key_component(policy.name, fallback="unknown_policy"),
            _hash_component(scope.tenant_id),
            _hash_component(scope.principal_scope),
            _hash_component(scope.source),
            _hash_component(scope.scenario),
            _hash_component(scope.capability),
        )
    )


def normalize_key_component(value: Any, *, fallback: str) -> str:
    raw = str(value or "").strip().lower()
    normalized = _SAFE_COMPONENT_RE.sub("_", raw).strip("_.-")
    if not normalized:
        return fallback
    normalized = normalized[:64]
    if normalized != raw:
        suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
        normalized = f"{normalized[:55]}-{suffix}"
    return normalized


def _hash_component(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _script_result(raw: Any) -> tuple[bool, float, int]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        raise ValueError("invalid Redis rate limit script response")
    return bool(int(raw[0])), float(raw[1]), max(0, int(raw[2]))
