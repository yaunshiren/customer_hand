from __future__ import annotations

from fastapi import Request

from app.api.schemas import MessageRequest
from app.entry.auth import (
    authenticate_request,
    require_admin_or_owner,
    require_any_role,
)
from app.entry.models import EntryTask, Principal
from app.entry.normalizer import normalize_message_request
from app.entry.rate_limit import enforce_rate_limit, enforce_rate_limit_for_principal

MESSAGE_ROLES = {"user", "evaluator", "admin"}


async def prepare_message_task(req: MessageRequest, request: Request) -> EntryTask:
    principal = authenticate_request(request)
    require_any_role(principal, MESSAGE_ROLES)
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
