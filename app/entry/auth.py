from __future__ import annotations

import hmac
from typing import Iterable

from fastapi import Request

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.entry.models import Principal
from app.settings import settings


PRODUCTION_ENVS = {"prod", "production"}


def authenticate_request(request: Request) -> Principal:
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.strip():
        return _principal_from_authorization(auth_header)

    api_key = request.headers.get("x-api-key")
    if api_key and api_key.strip():
        return _principal_from_credential(api_key.strip(), source="x_api_key")

    raise UnauthorizedError("API key is required")


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

    return _principal_from_credential(token.strip(), source="authorization_bearer")


def _principal_from_credential(token: str, *, source: str) -> Principal:
    profile = _find_api_key_profile(token)
    if profile is not None:
        return _principal_from_api_key_profile(profile, source=source)

    if token.startswith("dev:") and _dev_tokens_allowed():
        return _principal_from_dev_token(token)

    raise UnauthorizedError("invalid API key")


def _find_api_key_profile(token: str) -> dict[str, object] | None:
    matched: dict[str, object] | None = None
    for configured_key, profile in settings.api_key_principals.items():
        key = str(configured_key or "")
        if (
            key
            and hmac.compare_digest(token.encode("utf-8"), key.encode("utf-8"))
            and isinstance(profile, dict)
        ):
            matched = dict(profile)
    return matched


def _principal_from_api_key_profile(profile: dict[str, object], *, source: str) -> Principal:
    principal_id = str(profile.get("principal_id") or profile.get("user_id") or "").strip()
    tenant_id = str(profile.get("tenant_id") or "").strip()
    roles_value = profile.get("roles")
    roles = (
        [str(item).strip().lower() for item in roles_value if str(item).strip()]
        if isinstance(roles_value, list)
        else []
    )
    if not principal_id or not tenant_id or not roles:
        raise UnauthorizedError("invalid API key configuration")

    return Principal(
        principal_id=principal_id,
        user_id=principal_id,
        tenant_id=tenant_id,
        roles=roles,
        source=source,
        auth_type="api_key",
        data_scope={"tenant_id": tenant_id},
    )


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
        principal_id=user_id,
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles,
        source="dev_token",
        auth_type="dev_token",
        data_scope={"tenant_id": tenant_id},
    )


def _is_production() -> bool:
    return settings.app_env.strip().lower() in PRODUCTION_ENVS


def _dev_tokens_allowed() -> bool:
    return settings.auth_allow_dev_tokens and not _is_production()
