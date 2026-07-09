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


def prepare_message_task(req: MessageRequest, request: Request) -> EntryTask:
    principal = authenticate_request(request)
    require_any_role(principal, MESSAGE_ROLES)
    task = normalize_message_request(req, request, principal=principal)
    enforce_rate_limit(task, request)
    return task


def guard_eval_rag(request: Request) -> Principal:
    principal = authenticate_request(request)
    require_any_role(principal, {"evaluator", "admin"})
    enforce_rate_limit_for_principal(
        request=request,
        principal=principal,
        scenario="rag_eval",
        capability="rag",
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


def enforce_knowledge_reindex_rate_limit(request: Request, principal: Principal) -> None:
    enforce_rate_limit_for_principal(
        request=request,
        principal=principal,
        scenario="admin/reindex",
        capability="admin",
    )
