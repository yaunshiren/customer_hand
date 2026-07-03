from __future__ import annotations

import os
from typing import Iterable

from fastapi import Request

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.entry.models import Principal


PRODUCTION_ENVS = {"prod", "production"}


def authenticate_request(request: Request) -> Principal:
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.strip():
        return _principal_from_authorization(auth_header)

    if _is_production():
        raise UnauthorizedError("authorization required")

    return Principal(
        user_id="anonymous",
        tenant_id="default",
        roles=["anonymous"],
        auth_type="anonymous",
        data_scope={"anonymous_dev": True},
    )


def require_authenticated_or_dev_anonymous(principal: Principal) -> None:
    if principal.auth_type != "anonymous":
        return
    if "anonymous" in principal.roles and principal.data_scope.get("anonymous_dev") is True:
        return
    raise UnauthorizedError("authorization required")


def require_any_role(principal: Principal, allowed_roles: Iterable[str]) -> None:
    allowed = {role.strip().lower() for role in allowed_roles if role.strip()}
    actual = {role.strip().lower() for role in principal.roles or [] if role.strip()}
    if actual & allowed:
        return
    raise ForbiddenError("permission denied")


def require_admin_or_owner(principal: Principal, owner_user_id: str) -> None:
    roles = {role.strip().lower() for role in principal.roles or [] if role.strip()}
    if "admin" in roles:
        return
    if principal.user_id == str(owner_user_id).strip():
        return
    raise ForbiddenError("permission denied")


def _principal_from_authorization(value: str) -> Principal:
    scheme, _, token = value.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthorizedError("invalid authorization header")

    return _principal_from_dev_token(token.strip())


def _principal_from_dev_token(token: str) -> Principal:
    # Format: dev:user_001:tenant_demo:admin,evaluator
    parts = token.split(":")
    if len(parts) != 4 or parts[0] != "dev":
        raise UnauthorizedError("unsupported token format")

    _, user_id, tenant_id, roles_text = parts
    user_id = user_id.strip()
    tenant_id = tenant_id.strip()
    roles = [item.strip().lower() for item in roles_text.split(",") if item.strip()]

    if not user_id or not tenant_id or not roles:
        raise UnauthorizedError("invalid dev token")

    return Principal(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles,
        auth_type="dev_token",
        data_scope={"tenant_id": tenant_id},
    )


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in PRODUCTION_ENVS
