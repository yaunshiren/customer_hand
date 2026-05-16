from __future__ import annotations

import logging
from typing import Any

from app.core.trace import get_trace_id

_logger = logging.getLogger("app.telemetry")


def _short(value: Any, max_len: int = 120) -> str:
    s = repr(value)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def emit_llm_event(event: str, **fields: Any) -> None:
    tid = get_trace_id() or "-"
    parts = [f"{k}={_short(v)}" for k, v in fields.items()]
    _logger.info("llm.%s trace_id=%s %s", event, tid, " ".join(parts))


def emit_rag_event(event: str, **fields: Any) -> None:
    tid = get_trace_id() or "-"
    parts = [f"{k}={_short(v)}" for k, v in fields.items()]
    _logger.info("rag.%s trace_id=%s %s", event, tid, " ".join(parts))
