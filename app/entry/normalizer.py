from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import Request

from app.api.schemas import MessageRequest
from app.core.exceptions import BadRequestError, ForbiddenError
from app.core.trace import trace_id_from_request
from app.entry.models import EntrySource, EntryTask, Principal
from app.entry.security import build_security_flags


VALID_SOURCES = {"web", "app", "api", "webhook", "scheduler"}
TOOL_SCENARIOS = {
    "tool",
    "tool_write",
    "invoice",
    "ticket",
    "create_invoice",
    "create_ticket",
    "payment",
}


def normalize_message_request(
    req: MessageRequest,
    request: Request,
    *,
    principal: Principal,
) -> EntryTask:
    sender_id = _bind_sender_to_principal(req.sender_id, principal)
    raw_text = req.message or ""
    normalized_text = raw_text.strip()
    if not normalized_text:
        raise BadRequestError("message must not be empty")

    security_flags = build_security_flags(normalized_text)
    metadata = dict(getattr(req, "metadata", None) or {})
    metadata.setdefault("text_hash", security_flags.text_hash)

    conversation_id = str(getattr(req, "conversation_id", None) or sender_id).strip()
    source = _source(getattr(req, "source", None))
    scenario = _scenario(getattr(req, "scenario", None))
    capability = _capability_for_scenario(scenario)
    metadata["security_flags"] = security_flags.model_dump(mode="json", exclude_none=True)
    if security_flags.prompt_injection_risk and _requires_security_degrade(scenario, capability):
        metadata["security_degraded"] = True
        metadata["security_degrade_reason"] = "prompt_injection_risk"

    return EntryTask(
        trace_id=trace_id_from_request(request),
        request_id=_request_id(request),
        source=source,
        scenario=scenario,
        capability=capability,
        principal=principal,
        sender_id=sender_id,
        conversation_id=conversation_id,
        raw_text=raw_text,
        normalized_text=normalized_text,
        idempotency_key=_idempotency_key(request, metadata),
        security_flags=security_flags,
        metadata=metadata,
    )


def _bind_sender_to_principal(
    requested_sender_id: str | None,
    principal: Principal,
) -> str:
    trusted_sender_id = str(principal.user_id or "").strip()
    requested = str(requested_sender_id or "").strip()
    if requested and requested != trusted_sender_id:
        raise ForbiddenError("permission denied")
    return trusted_sender_id


def _request_id(request: Request) -> str:
    value = request.headers.get("x-request-id") or request.headers.get("x-trace-id")
    return str(value or "").strip() or uuid4().hex


def _source(value: Any) -> EntrySource:
    text = str(value or "api").strip().lower()
    if text not in VALID_SOURCES:
        return "api"
    return text  # type: ignore[return-value]


def _scenario(value: Any) -> str:
    return str(value or "chat").strip().lower() or "chat"


def _capability_for_scenario(scenario: str) -> str:
    if scenario in {"rag_eval", "knowledge_eval"}:
        return "rag"
    if scenario in TOOL_SCENARIOS:
        return "tool"
    return "chat"


def _requires_security_degrade(scenario: str, capability: str) -> bool:
    return capability == "tool" or scenario in TOOL_SCENARIOS


def _idempotency_key(request: Request, metadata: Any) -> str | None:
    header = request.headers.get("idempotency-key")
    if header and header.strip():
        return header.strip()
    if isinstance(metadata, dict):
        value = metadata.get("idempotency_key")
        if value and str(value).strip():
            return str(value).strip()
    return None
