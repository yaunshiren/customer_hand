from __future__ import annotations

import asyncio

import pytest
from starlette.requests import Request

from app.core.exceptions import RateLimitError
from app.entry.models import Principal
from app.entry.rate_limit import InMemoryRateLimiter, enforce_rate_limit_for_principal


def _request(ip: str = "10.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/probe",
            "headers": [(b"x-forwarded-for", ip.encode("latin-1"))],
            "client": (ip, 12345),
        }
    )


def _enforce(**kwargs) -> None:
    asyncio.run(enforce_rate_limit_for_principal(**kwargs))


def test_user_level_chat_rate_limit_returns_retry_after() -> None:
    limiter = InMemoryRateLimiter()
    principal = Principal(user_id="u1", tenant_id="tenant_a", roles=["user"], auth_type="dev_token")

    for _ in range(30):
        _enforce(
            request=_request(),
            principal=principal,
            scenario="chat",
            capability="chat",
            limiter=limiter,
        )

    with pytest.raises(RateLimitError) as exc:
        _enforce(
            request=_request(),
            principal=principal,
            scenario="chat",
            capability="chat",
            limiter=limiter,
        )

    assert exc.value.details["retry_after_seconds"] >= 1
    assert exc.value.details["rate_limit_policy"] == "chat_per_user"


def test_tenant_level_reindex_rate_limit_is_shared_by_tenant() -> None:
    limiter = InMemoryRateLimiter()
    first = Principal(user_id="admin1", tenant_id="tenant_a", roles=["admin"], auth_type="dev_token")
    second = Principal(user_id="admin2", tenant_id="tenant_a", roles=["admin"], auth_type="dev_token")

    _enforce(
        request=_request(),
        principal=first,
        scenario="admin/reindex",
        capability="admin",
        limiter=limiter,
    )

    with pytest.raises(RateLimitError):
        _enforce(
            request=_request(),
            principal=second,
            scenario="admin/reindex",
            capability="admin",
            limiter=limiter,
        )


def test_anonymous_rate_limit_is_keyed_by_ip() -> None:
    limiter = InMemoryRateLimiter()
    principal = Principal()

    for _ in range(10):
        _enforce(
            request=_request("10.0.0.9"),
            principal=principal,
            scenario="chat",
            capability="chat",
            limiter=limiter,
        )

    with pytest.raises(RateLimitError):
        _enforce(
            request=_request("10.0.0.9"),
            principal=principal,
            scenario="chat",
            capability="chat",
            limiter=limiter,
        )
