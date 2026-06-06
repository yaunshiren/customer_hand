from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping
from typing import Any

from app.core.trace import get_trace_id
from app.persistence.db import trace_db_session
from app.persistence.repositories import RetrievalTraceCreate, TraceRepository

logger = logging.getLogger(__name__)


class RetrievalTraceRecorder:
    """Best-effort writer for RAG retrieval traces."""

    def __init__(self, failure_cooldown_seconds: float = 30.0) -> None:
        self.failure_cooldown_seconds = failure_cooldown_seconds
        self._disabled_until = 0.0

    def record(
        self,
        *,
        query: str,
        records: Iterable[RetrievalTraceCreate | Mapping[str, Any]],
        trace_id: str | None = None,
    ) -> None:
        tid = (trace_id or get_trace_id() or "").strip()
        if not tid:
            return

        items = [_with_query(query, record) for record in records]
        if not items:
            return

        self._safe_write(
            "retrieval_trace.write",
            lambda repo: repo.add_retrieval_traces(tid, items),
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


_default_recorder = RetrievalTraceRecorder()


def record_retrieval_traces(
    *,
    query: str,
    records: Iterable[RetrievalTraceCreate | Mapping[str, Any]],
    trace_id: str | None = None,
) -> None:
    _default_recorder.record(query=query, records=records, trace_id=trace_id)


def _with_query(
    query: str,
    record: RetrievalTraceCreate | Mapping[str, Any],
) -> RetrievalTraceCreate | Mapping[str, Any]:
    if isinstance(record, RetrievalTraceCreate):
        if record.query:
            return record
        return RetrievalTraceCreate(
            query=query,
            channel=record.channel,
            doc_id=record.doc_id,
            chunk_id=record.chunk_id,
            score=record.score,
            rerank_score=record.rerank_score,
            content=record.content,
            created_at=record.created_at,
        )

    data = dict(record)
    data.setdefault("query", query)
    return data
