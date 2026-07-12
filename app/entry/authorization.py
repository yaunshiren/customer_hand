from __future__ import annotations

from dataclasses import dataclass

from app.core.exceptions import ForbiddenError
from app.entry.models import Principal


TRUSTED_RESOURCE_AUTH_TYPES = frozenset({"api_key", "jwt", "system"})
RESOURCE_ROLES = frozenset({"user", "evaluator", "admin"})


@dataclass(frozen=True, slots=True, init=False)
class AuthorizedContext:
    """Trusted, immutable tenant/owner scope derived from a server Principal."""

    principal_id: str
    tenant_id: str
    roles: frozenset[str]
    owner_user_id: str

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("AuthorizedContext must be created from a Principal")

    @classmethod
    def from_principal(cls, principal: Principal) -> "AuthorizedContext":
        if not isinstance(principal, Principal):
            raise ForbiddenError("permission denied")
        if principal.auth_type not in TRUSTED_RESOURCE_AUTH_TYPES:
            raise ForbiddenError("permission denied")

        principal_id = str(principal.principal_id or "").strip()
        owner_user_id = str(principal.user_id or "").strip()
        tenant_id = str(principal.tenant_id or "").strip()
        roles = frozenset(
            str(role).strip().lower()
            for role in principal.roles or []
            if str(role).strip()
        )
        if (
            not principal_id
            or principal_id != owner_user_id
            or not tenant_id
            or (principal.auth_type == "system" and tenant_id == "default")
            or not roles
            or not roles.intersection(RESOURCE_ROLES)
        ):
            raise ForbiddenError("permission denied")

        context = object.__new__(cls)
        object.__setattr__(context, "principal_id", principal_id)
        object.__setattr__(context, "tenant_id", tenant_id)
        object.__setattr__(context, "roles", roles)
        object.__setattr__(context, "owner_user_id", owner_user_id)
        return context

    @property
    def is_tenant_admin(self) -> bool:
        return "admin" in self.roles
