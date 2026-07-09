from __future__ import annotations

from fastapi import Request

from app.core.exceptions import RateLimitError
from app.entry.models import EntryTask, Principal
from app.entry.rate_limit_store import (
    InMemoryRateLimiter,
    RateLimitDecision,
    RateLimiterProtocol,
    RateLimitPolicy,
    RateLimitScope,
    RedisRateLimiter,
)
from app.settings import settings


TOOL_SCENARIOS = {
    "tool",
    "tool_write",
    "ticket",
    "create_ticket",
    "invoice",
    "create_invoice",
}
RAG_EVAL_SCENARIOS = {"rag_eval", "knowledge_eval"}
ADMIN_REINDEX_SCENARIOS = {"admin/reindex", "admin_reindex"}

_default_limiter: RateLimiterProtocol | None = None


async def enforce_rate_limit(
    task: EntryTask,
    request: Request,
    *,
    limiter: RateLimiterProtocol | None = None,
) -> None:
    await enforce_rate_limit_for_principal(
        request=request,
        principal=task.principal,
        source=task.source,
        scenario=task.scenario,
        capability=task.capability,
        limiter=limiter,
    )


async def enforce_rate_limit_for_principal(
    *,
    request: Request,
    principal: Principal,
    scenario: str,
    capability: str,
    source: str = "api",
    limiter: RateLimiterProtocol | None = None,
) -> None:
    active_limiter = limiter or get_rate_limiter()
    for scope, policy in _rate_limit_checks(
        request,
        principal,
        source=source,
        scenario=scenario,
        capability=capability,
    ):
        decision = await active_limiter.check(scope, policy)
        if not decision.allowed:
            raise RateLimitError(
                "rate limit exceeded",
                details={
                    "retry_after_seconds": decision.retry_after_seconds,
                    "rate_limit_key": decision.key,
                    "rate_limit_policy": decision.policy.name,
                },
            )


def build_rate_limiter() -> RateLimiterProtocol:
    if settings.rate_limit_backend == "redis":
        return RedisRateLimiter(
            settings.redis_url,
            key_prefix=settings.rate_limit_key_prefix,
        )
    return InMemoryRateLimiter(key_prefix=settings.rate_limit_key_prefix)


def get_rate_limiter() -> RateLimiterProtocol:
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = build_rate_limiter()
    return _default_limiter


def reset_rate_limiter() -> None:
    limiter = get_rate_limiter()
    if isinstance(limiter, InMemoryRateLimiter):
        limiter.reset()


async def close_rate_limiter(limiter: RateLimiterProtocol | None = None) -> None:
    active_limiter = limiter or _default_limiter
    if active_limiter is not None:
        await active_limiter.aclose()


def _rate_limit_checks(
    request: Request,
    principal: Principal,
    *,
    source: str,
    scenario: str,
    capability: str,
) -> list[tuple[RateLimitScope, RateLimitPolicy]]:
    normalized_source = str(source or "api").strip().lower() or "api"
    normalized_scenario = str(scenario or "chat").strip().lower() or "chat"
    normalized_capability = str(capability or "chat").strip().lower() or "chat"
    tenant_id = str(principal.tenant_id or "default").strip() or "default"
    principal_id = str(principal.principal_id or "anonymous").strip() or "anonymous"

    if principal.auth_type == "anonymous":
        return [
            (
                RateLimitScope(
                    tenant_id=tenant_id,
                    principal_scope=f"anonymous-ip:{_client_ip(request)}",
                    source=normalized_source,
                    scenario=normalized_scenario,
                    capability=normalized_capability,
                ),
                _anonymous_policy(),
            )
        ]

    if normalized_scenario in ADMIN_REINDEX_SCENARIOS:
        return [
            (
                RateLimitScope(
                    tenant_id=tenant_id,
                    principal_scope="tenant-wide",
                    source=normalized_source,
                    scenario="admin_reindex",
                    capability=normalized_capability,
                ),
                _admin_reindex_policy(),
            )
        ]

    policy = _policy_for(normalized_scenario, normalized_capability)
    if policy is None:
        return []
    return [
        (
            RateLimitScope(
                tenant_id=tenant_id,
                principal_scope=principal_id,
                source=normalized_source,
                scenario=normalized_scenario,
                capability=normalized_capability,
            ),
            policy,
        )
    ]


def _policy_for(scenario: str, capability: str) -> RateLimitPolicy | None:
    if scenario in RAG_EVAL_SCENARIOS:
        return _rag_eval_policy()
    if scenario in TOOL_SCENARIOS or capability in {
        "tool",
        "tool_write",
        "ticket",
        "invoice",
    }:
        return _tool_policy()
    if scenario == "chat":
        return _chat_policy()
    return None


def _chat_policy() -> RateLimitPolicy:
    return RateLimitPolicy(
        name="chat_per_user",
        capacity=settings.rate_limit_chat_capacity,
        window_seconds=settings.rate_limit_chat_window_seconds,
    )


def _tool_policy() -> RateLimitPolicy:
    return RateLimitPolicy(
        name="tool_per_user",
        capacity=settings.rate_limit_tool_capacity,
        window_seconds=settings.rate_limit_tool_window_seconds,
    )


def _rag_eval_policy() -> RateLimitPolicy:
    return RateLimitPolicy(
        name="rag_eval_per_user",
        capacity=settings.rate_limit_rag_eval_capacity,
        window_seconds=settings.rate_limit_rag_eval_window_seconds,
    )


def _admin_reindex_policy() -> RateLimitPolicy:
    return RateLimitPolicy(
        name="admin_reindex_per_tenant",
        capacity=settings.rate_limit_admin_reindex_capacity,
        window_seconds=settings.rate_limit_admin_reindex_window_seconds,
    )


def _anonymous_policy() -> RateLimitPolicy:
    return RateLimitPolicy(
        name="anonymous_per_ip",
        capacity=settings.rate_limit_anonymous_capacity,
        window_seconds=settings.rate_limit_anonymous_window_seconds,
    )


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first = forwarded_for.split(",", 1)[0].strip()
        if first:
            return first
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host or "unknown").strip() or "unknown"


__all__ = [
    "InMemoryRateLimiter",
    "RateLimitDecision",
    "RateLimitPolicy",
    "RateLimitScope",
    "RedisRateLimiter",
    "build_rate_limiter",
    "close_rate_limiter",
    "enforce_rate_limit",
    "enforce_rate_limit_for_principal",
    "get_rate_limiter",
    "reset_rate_limiter",
]
