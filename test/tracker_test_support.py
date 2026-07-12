from __future__ import annotations

from app.entry.authorization import AuthorizedContext
from app.entry.models import Principal


def trusted_test_principal(
    user_id: str,
    *,
    tenant_id: str = "tenant_test",
    roles: list[str] | None = None,
) -> Principal:
    return Principal(
        principal_id=user_id,
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles or ["user"],
        source="test_setup",
        auth_type="system",
    )


def tracker_context(
    user_id: str,
    *,
    tenant_id: str = "tenant_test",
    roles: list[str] | None = None,
) -> AuthorizedContext:
    return AuthorizedContext.from_principal(
        trusted_test_principal(
            user_id,
            tenant_id=tenant_id,
            roles=roles,
        )
    )
