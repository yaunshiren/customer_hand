from __future__ import annotations

from fastapi import Request

from app.api.schemas import MessageRequest
from app.core.exceptions import ForbiddenError
from app.entry.authorization import AuthorizedContext
from app.entry.auth import (
    authenticate_request,
    require_any_role,
)
from app.entry.models import EntryTask, Principal
from app.entry.normalizer import normalize_message_request
from app.entry.rate_limit import enforce_rate_limit, enforce_rate_limit_for_principal

MESSAGE_ROLES = {"user", "evaluator", "admin"}
TRACKER_READ_ROLES = {"user", "admin"}


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


def guard_tracker_reset(request: Request, sender_id: str) -> AuthorizedContext:
    return _guard_tracker_resource(request, sender_id)


def guard_tracker_full(request: Request, sender_id: str) -> AuthorizedContext:
    return _guard_tracker_resource(request, sender_id)


def _guard_tracker_resource(
    request: Request,
    sender_id: str,
) -> AuthorizedContext:
    principal = authenticate_request(request)
    require_any_role(principal, TRACKER_READ_ROLES)
    _require_trusted_principal(principal)

    context = AuthorizedContext.from_principal(principal)
    target_owner = str(sender_id or "").strip()
    if not target_owner:
        raise ForbiddenError("permission denied")
    if target_owner != context.owner_user_id and not context.is_tenant_admin:
        raise ForbiddenError("permission denied")
    return context


def guard_inspect_page(request: Request) -> Principal:
    principal = authenticate_request(request)
    require_any_role(principal, {"admin"})
    _require_trusted_principal(principal)
    return principal


def _require_trusted_principal(principal: Principal) -> None:
    AuthorizedContext.from_principal(principal)


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
