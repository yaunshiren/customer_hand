from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from fastapi import Request

from app.core.exceptions import RateLimitError
from app.entry.models import EntryTask, Principal


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    capacity: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    key: str
    policy: RateLimitPolicy
    retry_after_seconds: int = 0
    remaining: int = 0


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


CHAT_POLICY = RateLimitPolicy(name="chat_per_user", capacity=30, window_seconds=60)
RAG_EVAL_POLICY = RateLimitPolicy(name="rag_eval_per_user", capacity=10, window_seconds=60)
TOOL_POLICY = RateLimitPolicy(name="tool_per_user", capacity=5, window_seconds=60)
REINDEX_POLICY = RateLimitPolicy(name="admin_reindex_per_tenant", capacity=1, window_seconds=3600)
ANONYMOUS_POLICY = RateLimitPolicy(name="anonymous_per_ip", capacity=10, window_seconds=60)

SCENARIO_POLICIES: dict[str, RateLimitPolicy] = {
    "chat": CHAT_POLICY,
    "rag_eval": RAG_EVAL_POLICY,
    "knowledge_eval": RAG_EVAL_POLICY,
    "tool": TOOL_POLICY,
    "ticket": TOOL_POLICY,
    "create_ticket": TOOL_POLICY,
    "invoice": TOOL_POLICY,
    "create_invoice": TOOL_POLICY,
}


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str, policy: RateLimitPolicy, *, now: float | None = None) -> RateLimitDecision:
        current = time.monotonic() if now is None else now
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
                    remaining=int(tokens),
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


_default_limiter = InMemoryRateLimiter()


def enforce_rate_limit(
    task: EntryTask,
    request: Request,
    *,
    limiter: InMemoryRateLimiter | None = None,
) -> None:
    enforce_rate_limit_for_principal(
        request=request,
        principal=task.principal,
        scenario=task.scenario,
        capability=task.capability,
        limiter=limiter,
    )


def enforce_rate_limit_for_principal(
    *,
    request: Request,
    principal: Principal,
    scenario: str,
    capability: str,
    limiter: InMemoryRateLimiter | None = None,
) -> None:
    active_limiter = limiter or _default_limiter
    for key, policy in _rate_limit_checks(request, principal, scenario=scenario, capability=capability):
        decision = active_limiter.check(key, policy)
        if not decision.allowed:
            raise RateLimitError(
                "rate limit exceeded",
                details={
                    "retry_after_seconds": decision.retry_after_seconds,
                    "rate_limit_key": decision.key,
                    "rate_limit_policy": decision.policy.name,
                },
            )


def reset_rate_limiter() -> None:
    _default_limiter.reset()


def _rate_limit_checks(
    request: Request,
    principal: Principal,
    *,
    scenario: str,
    capability: str,
) -> list[tuple[str, RateLimitPolicy]]:
    normalized_scenario = str(scenario or "chat").strip().lower() or "chat"
    normalized_capability = str(capability or "chat").strip().lower() or "chat"
    tenant_id = str(principal.tenant_id or "default").strip() or "default"
    user_id = str(principal.user_id or "anonymous").strip() or "anonymous"

    if principal.auth_type == "anonymous":
        return [(f"ip:{_client_ip(request)}:anonymous", ANONYMOUS_POLICY)]

    checks: list[tuple[str, RateLimitPolicy]] = []
    if normalized_scenario == "admin/reindex":
        checks.append(
            (
                f"tenant:{tenant_id}:capability:{normalized_capability}:scenario:{normalized_scenario}",
                REINDEX_POLICY,
            )
        )

    policy = SCENARIO_POLICIES.get(normalized_scenario)
    if policy is not None:
        checks.append((f"tenant:{tenant_id}:user:{user_id}:scenario:{normalized_scenario}", policy))

    return checks


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first = forwarded_for.split(",", 1)[0].strip()
        if first:
            return first
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host or "unknown").strip() or "unknown"
