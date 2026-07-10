from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from app.api.schemas import MessageRequest, MessageResponse
from app.core.trace import run_with_trace, trace_id_from_request, trace_scope
from app.entry.guard import prepare_message_task
from app.entry.idempotency import run_with_idempotency, safe_response_snapshot
from app.entry.models import EntryTask
from app.persistence.trace_recorder import AgentTraceRecorder
from app.skills import context_from_entry_task, skill_context_scope

logger = logging.getLogger(__name__)


def _trace_user_text(task: EntryTask) -> str:
    if task.security_flags.redacted_text:
        return task.security_flags.redacted_text
    if task.security_flags.text_hash:
        return f"<text_hash:{task.security_flags.text_hash}>"
    return "<empty_text>"


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _response_metadata(responses: list[MessageResponse]) -> dict[str, Any]:
    if not responses:
        return {}
    return dict(responses[0].metadata or {})


def _memory_snapshot(metadata: dict[str, Any]) -> dict[str, Any] | None:
    value = metadata.get("memory_snapshot")
    snapshot = dict(value) if isinstance(value, dict) else None
    query_rewrite = metadata.get("query_rewrite")
    if isinstance(query_rewrite, dict):
        snapshot = snapshot or {}
        snapshot["query_rewrite"] = dict(query_rewrite)
    return snapshot


def _final_answer(responses: list[MessageResponse]) -> str | None:
    texts = [str(item.text).strip() for item in responses if item.text and str(item.text).strip()]
    if not texts:
        return None
    return "\n".join(texts)


def _first_intent_id(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("intentLeafIds")
    if isinstance(value, list) and value:
        text = str(value[0]).strip()
        return text or None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def prepare_entry_task(req: MessageRequest, request: Request) -> EntryTask:
    return await prepare_message_task(req, request)


async def run_agent(task: EntryTask, request: Request) -> list[dict[str, object]]:
    def handle() -> list[dict[str, object]]:
        # The scope is created inside the worker thread used by run_with_trace.
        # ContextVar.reset in the context manager's finally prevents worker-thread
        # reuse from leaking a principal, tenant, or idempotency key across requests.
        with skill_context_scope(context_from_entry_task(task)):
            return request.app.state.agent.handle_task(task)

    return await run_with_trace(request, handle)


def build_message_response(
    raw_responses: list[dict[str, object]],
    task: EntryTask,
) -> list[MessageResponse]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        MessageResponse(
            recipient_id=str(item.get("recipient_id", task.sender_id)),
            text=item.get("text"),
            timestamp=str(item.get("timestamp") or now),
            metadata=dict(item.get("metadata") or {}),
        )
        for item in raw_responses
    ]


async def handle_idempotency(
    task: EntryTask,
    request: Request,
    execute_request: Callable[[], Awaitable[list[MessageResponse]]],
) -> list[MessageResponse]:
    return await run_with_idempotency(
        task,
        request,
        execute_request,
        store=request.app.state.idempotency_store,
        snapshot_encoder=lambda responses: safe_response_snapshot(
            responses,
            secrets=(task.raw_text, task.normalized_text),
        ),
        snapshot_decoder=_decode_message_response_snapshot,
    )


def _decode_message_response_snapshot(value: Any) -> list[MessageResponse]:
    if not isinstance(value, list):
        raise ValueError("message response snapshot must be a list")
    return [MessageResponse.model_validate(item) for item in value]


def record_agent_trace_start(
    recorder: AgentTraceRecorder,
    *,
    trace_id: str,
    task: EntryTask,
    user_text: str,
) -> None:
    recorder.record_message_start(
        trace_id=trace_id,
        sender_id=task.sender_id,
        conversation_id=task.conversation_id,
        user_text=user_text,
    )


def record_agent_trace_success(
    recorder: AgentTraceRecorder,
    *,
    trace_id: str,
    task: EntryTask,
    user_text: str,
    responses: list[MessageResponse],
    started_at: float,
) -> None:
    metadata = _response_metadata(responses)
    recorder.record_message_success(
        trace_id=trace_id,
        sender_id=task.sender_id,
        conversation_id=task.conversation_id,
        user_text=user_text,
        rewritten_query=metadata.get("rewritten_query") or None,
        memory_snapshot=_memory_snapshot(metadata),
        intent_id=_first_intent_id(metadata),
        intent_confidence=_optional_float(metadata.get("intentConfidence")),
        route=str(metadata.get("route") or "").strip() or None,
        final_answer=_final_answer(responses),
        latency_ms=_elapsed_ms(started_at),
    )


def record_agent_trace_error(
    recorder: AgentTraceRecorder,
    *,
    trace_id: str,
    task: EntryTask,
    user_text: str,
    error: Exception,
    started_at: float,
) -> None:
    recorder.record_message_error(
        trace_id=trace_id,
        sender_id=task.sender_id,
        conversation_id=task.conversation_id,
        user_text=user_text,
        error=error,
        latency_ms=_elapsed_ms(started_at),
    )


async def process_message(req: MessageRequest, request: Request) -> list[MessageResponse]:
    trace_id = trace_id_from_request(request)
    started_at = time.perf_counter()
    task = await prepare_entry_task(req, request)
    recorder: AgentTraceRecorder = request.app.state.trace_recorder

    with trace_scope(trace_id):
        trace_text = _trace_user_text(task)
        logger.info(
            "api.messages sender_id=%s source=%s scenario=%s capability=%s message_len=%d",
            task.sender_id,
            task.source,
            task.scenario,
            task.capability,
            len(task.normalized_text),
        )
        record_agent_trace_start(
            recorder,
            trace_id=trace_id,
            task=task,
            user_text=trace_text,
        )

        async def execute_request() -> list[MessageResponse]:
            raw_responses = await run_agent(task, request)
            return build_message_response(raw_responses, task)

        try:
            responses = await handle_idempotency(task, request, execute_request)
            record_agent_trace_success(
                recorder,
                trace_id=trace_id,
                task=task,
                user_text=trace_text,
                responses=responses,
                started_at=started_at,
            )
            logger.info("api.messages.done sender_id=%s replies=%d", task.sender_id, len(responses))
            return responses
        except Exception as exc:
            record_agent_trace_error(
                recorder,
                trace_id=trace_id,
                task=task,
                user_text=trace_text,
                error=exc,
                started_at=started_at,
            )
            raise
