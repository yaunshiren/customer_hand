from __future__ import annotations

import logging
import time
from typing import Any

from app.persistence.db import trace_db_session
from app.persistence.repositories import AgentTraceCreate, TraceRepository

logger = logging.getLogger(__name__)


class AgentTraceRecorder:
    """Best-effort writer for request-level agent traces.

    Trace persistence must not decide user-facing API success. Failures are logged
    and the request continues, while successful writes remain fully structured.
    """

    def __init__(self, failure_cooldown_seconds: float = 30.0) -> None:
        self.failure_cooldown_seconds = failure_cooldown_seconds
        self._disabled_until = 0.0

    def record_message_start(
        self,
        *,
        trace_id: str,
        sender_id: str,
        conversation_id: str | None,
        user_text: str,
    ) -> None:
        self._safe_write(
            "agent_trace.start",
            lambda repo: self._ensure_started(
                repo=repo,
                trace_id=trace_id,
                sender_id=sender_id,
                conversation_id=conversation_id,
                user_text=user_text,
            ),
        )

    def record_message_success(
        self,
        *,
        trace_id: str,
        sender_id: str,
        conversation_id: str | None,
        user_text: str,
        rewritten_query: str | None,
        memory_snapshot: dict[str, Any] | None,
        intent_id: str | None,
        intent_confidence: float | None,
        route: str | None,
        final_answer: str | None,
        latency_ms: int,
    ) -> None:
        fields = {
            "conversation_id": conversation_id,
            "rewritten_query": rewritten_query,
            "memory_snapshot": memory_snapshot,
            "intent_id": intent_id,
            "intent_confidence": intent_confidence,
            "route": route,
            "final_answer": final_answer,
            "latency_ms": latency_ms,
        }
        self._safe_write(
            "agent_trace.success",
            lambda repo: self._update_or_create(
                repo=repo,
                trace_id=trace_id,
                sender_id=sender_id,
                user_text=user_text,
                **fields,
            ),
        )

    def record_message_error(
        self,
        *,
        trace_id: str,
        sender_id: str,
        conversation_id: str | None,
        user_text: str,
        error: BaseException | str,
        latency_ms: int,
        route: str = "error",
    ) -> None:
        error_text = _error_summary(error)
        self._safe_write(
            "agent_trace.error",
            lambda repo: self._update_or_create(
                repo=repo,
                trace_id=trace_id,
                sender_id=sender_id,
                conversation_id=conversation_id,
                user_text=user_text,
                rewritten_query=None,
                memory_snapshot=None,
                intent_id=None,
                intent_confidence=None,
                route=route,
                final_answer=error_text,
                latency_ms=latency_ms,
            ),
        )

    def _ensure_started(
        self,
        *,
        repo: TraceRepository,
        trace_id: str,
        sender_id: str,
        conversation_id: str | None,
        user_text: str,
    ) -> None:
        updated = repo.update_agent_trace(trace_id, conversation_id=conversation_id)
        if updated is not None:
            return

        repo.create_agent_trace(
            AgentTraceCreate(
                id=trace_id,
                sender_id=sender_id,
                conversation_id=conversation_id,
                user_text=user_text,
            )
        )

    def _update_or_create(
        self,
        *,
        repo: TraceRepository,
        trace_id: str,
        sender_id: str,
        conversation_id: str | None,
        user_text: str,
        rewritten_query: str | None,
        memory_snapshot: dict[str, Any] | None,
        intent_id: str | None,
        intent_confidence: float | None,
        route: str | None,
        final_answer: str | None,
        latency_ms: int,
    ) -> None:
        updated = repo.update_agent_trace(
            trace_id,
            conversation_id=conversation_id,
            rewritten_query=rewritten_query,
            memory_snapshot=memory_snapshot,
            intent_id=intent_id,
            intent_confidence=intent_confidence,
            route=route,
            final_answer=final_answer,
            latency_ms=latency_ms,
        )
        if updated is not None:
            return

        repo.create_agent_trace(
            AgentTraceCreate(
                id=trace_id,
                sender_id=sender_id,
                conversation_id=conversation_id,
                user_text=user_text,
                rewritten_query=rewritten_query,
                memory_snapshot=memory_snapshot,
                intent_id=intent_id,
                intent_confidence=intent_confidence,
                route=route,
                final_answer=final_answer,
                latency_ms=latency_ms,
            )
        )

    def _safe_write(self, event: str, operation: Any) -> None:
        now = time.monotonic()
        if now < self._disabled_until:
            return

        try:
            with trace_db_session() as session:
                operation(TraceRepository(session))
        except Exception as exc:
            self._disabled_until = time.monotonic() + self.failure_cooldown_seconds
            logger.warning("%s failed: %s", event, exc, exc_info=True)


def _error_summary(error: BaseException | str, max_len: int = 1000) -> str:
    if isinstance(error, BaseException):
        text = f"{error.__class__.__name__}: {error}"
    else:
        text = str(error)
    text = text.strip() or "unknown error"
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text
