from __future__ import annotations

import logging
import time
from typing import Any

from app.core.trace import get_trace_id
from app.persistence.db import trace_db_session
from app.persistence.repositories import ToolTraceCreate, TraceRepository

logger = logging.getLogger(__name__)


class ToolTraceRecorder:
    """Best-effort writer for action/tool execution traces."""

    def __init__(self, failure_cooldown_seconds: float = 30.0) -> None:
        self.failure_cooldown_seconds = failure_cooldown_seconds
        self._disabled_until = 0.0

    def record(
        self,
        *,
        tool_name: str,
        arguments_json: Any = None,
        result_json: Any = None,
        status: str,
        latency_ms: int | None = None,
        trace_id: str | None = None,
    ) -> None:
        tid = (trace_id or get_trace_id() or "").strip()
        if not tid:
            return

        self._safe_write(
            "tool_trace.write",
            lambda repo: repo.add_tool_trace(
                ToolTraceCreate(
                    trace_id=tid,
                    tool_name=tool_name,
                    arguments_json=arguments_json,
                    result_json=result_json,
                    status=status,
                    latency_ms=latency_ms,
                )
            ),
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


_default_recorder = ToolTraceRecorder()


def record_tool_trace(
    *,
    tool_name: str,
    arguments_json: Any = None,
    result_json: Any = None,
    status: str,
    latency_ms: int | None = None,
    trace_id: str | None = None,
) -> None:
    _default_recorder.record(
        tool_name=tool_name,
        arguments_json=arguments_json,
        result_json=result_json,
        status=status,
        latency_ms=latency_ms,
        trace_id=trace_id,
    )
