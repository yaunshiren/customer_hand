from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import Request

from app.api.schemas import MessageRequest
from app.core.exceptions import BadRequestError
from app.core.trace import trace_id_from_request
from app.entry.models import EntrySource, EntryTask, Principal
from app.entry.security import build_security_flags


VALID_SOURCES = {"web", "app", "api", "webhook", "scheduler"}


def normalize_message_request(
    req: MessageRequest,
    request: Request,
    *,
    principal: Principal | None = None,
) -> EntryTask:
    raw_text = req.message or ""
    normalized_text = raw_text.strip()
    if not normalized_text:
        raise BadRequestError("message must not be empty")
    
    security_flags = build_security_flags(normalized_text)
    metadata = dict(getattr(req, "metadata", None) or {})
    metadata.setdefault("text_hash", security_flags.text_hash)

    sender_id = str(req.sender_id or "").strip() or "user"
    conversation_id = str(getattr(req, "conversation_id", None) or sender_id).strip()
    source = _source(getattr(req, "source", None))
    scenario = str(getattr(req, "scenario", None) or "chat").strip() or "chat"

    return EntryTask(
        trace_id=trace_id_from_request(request),
        request_id=_request_id(request),
        source=source,
        scenario=scenario,
        capability=_capability_for_scenario(scenario),
        principal=principal or Principal(user_id=sender_id, tenant_id="default", roles=["user"]),
        sender_id=sender_id,
        conversation_id=conversation_id,
        raw_text=raw_text,
        normalized_text=normalized_text,
        idempotency_key=_idempotency_key(request, metadata),
        security_flags=security_flags,
        metadata=metadata,
    )


def _request_id(request: Request) -> str:
    value = request.headers.get("x-request-id") or request.headers.get("x-trace-id")
    return str(value or "").strip() or uuid4().hex


def _source(value: Any) -> EntrySource:
    text = str(value or "api").strip().lower()
    if text not in VALID_SOURCES:
        return "api"
    return text  # type: ignore[return-value]


def _capability_for_scenario(scenario: str) -> str:
    if scenario in {"rag_eval", "knowledge_eval"}:
        return "rag"
    if scenario in {"tool", "invoice", "ticket"}:
        return "tool"
    return "chat"


def _idempotency_key(request: Request, metadata: Any) -> str | None:
    header = request.headers.get("idempotency-key")
    if header and header.strip():
        return header.strip()
    if isinstance(metadata, dict):
        value = metadata.get("idempotency_key")
        if value and str(value).strip():
            return str(value).strip()
    return None