from __future__ import annotations

from fastapi import Request

from app.api.schemas import MessageRequest
from app.core.exceptions import ForbiddenError
from app.entry.auth import (
    authenticate_request,
    require_admin_or_owner,
    require_any_role,
)
from app.entry.models import EntryTask, Principal
from app.entry.normalizer import normalize_message_request
from app.entry.rate_limit import enforce_rate_limit, enforce_rate_limit_for_principal

MESSAGE_ROLES = {"user", "evaluator", "admin"}
TRACKER_READ_ROLES = {"user", "admin"}
TRUSTED_RESOURCE_AUTH_TYPES = {"api_key", "jwt"}


async def prepare_message_task(req: MessageRequest, request: Request) -> EntryTask:
    principal = authenticate_request(request)
    require_any_role(principal, MESSAGE_ROLES)
    # A client-authored dev token cannot establish a trustworthy sender.
    _require_trusted_principal(principal)
    task = normalize_message_request(req, request, principal=principal)
    await enforce_rate_limit(
        task,
        request,
        limiter=request.app.state.rate_limiter,
    )
    return task


async def guard_eval_rag(request: Request) -> Principal:
    principal = authenticate_request(request)
    require_any_role(principal, {"evaluator", "admin"})
    await enforce_rate_limit_for_principal(
        request=request,
        principal=principal,
        source="api",
        scenario="rag_eval",
        capability="rag",
        limiter=request.app.state.rate_limiter,
    )
    return principal


def guard_tracker_reset(request: Request, sender_id: str) -> Principal:
    principal = authenticate_request(request)
    require_admin_or_owner(principal, sender_id)
    return principal


def guard_tracker_full(request: Request, sender_id: str) -> Principal:
    principal = authenticate_request(request)
    require_any_role(principal, TRACKER_READ_ROLES)

    # Dev tokens carry client-authored identity and role fields. They remain a
    # compatibility option for other development flows, but are not reliable
    # enough to authorize a full Tracker read.
    _require_trusted_principal(principal)

    # Tracker currently has no tenant field. An admin role alone therefore
    # cannot prove that an arbitrary Tracker belongs to the admin's tenant.
    # Restrict reads to the authenticated identity until tenant ownership is
    # represented by the resource model.
    if principal.user_id.strip() != str(sender_id or "").strip():
        raise ForbiddenError("permission denied")
    return principal


def guard_inspect_page(request: Request) -> Principal:
    principal = authenticate_request(request)
    require_any_role(principal, {"admin"})
    _require_trusted_principal(principal)
    return principal


def _require_trusted_principal(principal: Principal) -> None:
    if principal.auth_type not in TRUSTED_RESOURCE_AUTH_TYPES:
        raise ForbiddenError("permission denied")


def guard_knowledge_reindex(request: Request) -> Principal:
    principal = authenticate_request(request)
    require_any_role(principal, {"admin"})
    return principal


async def enforce_knowledge_reindex_rate_limit(
    request: Request,
    principal: Principal,
) -> None:
    await enforce_rate_limit_for_principal(
        request=request,
        principal=principal,
        source="api",
        scenario="admin_reindex",
        capability="admin_reindex",
        limiter=request.app.state.rate_limiter,
    )
