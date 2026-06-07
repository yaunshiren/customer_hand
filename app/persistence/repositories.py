from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.persistence.models import AgentTrace, EvalRecord, RetrievalTrace, ToolTrace

TOOL_STATUSES = {"success", "failed"}
EVAL_ERROR_TYPES = {
    "INTENT_ERROR",
    "ROUTE_ERROR",
    "RETRIEVAL_MISS",
    "RERANK_ERROR",
    "CONTEXT_TOO_NOISY",
    "GENERATION_HALLUCINATION",
    "TOOL_ARGUMENT_ERROR",
    "TOOL_FAILURE",
    "KNOWLEDGE_MISSING",
    "PROMPT_ERROR",
}


@dataclass(frozen=True, slots=True)
class AgentTraceCreate:
    id: str
    sender_id: str
    user_text: str
    conversation_id: str | None = None
    rewritten_query: str | None = None
    intent_id: str | None = None
    intent_confidence: float | None = None
    route: str | None = None
    final_answer: str | None = None
    latency_ms: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RetrievalTraceCreate:
    query: str
    channel: str
    doc_id: str | None = None
    chunk_id: str | None = None
    score: float | None = None
    rerank_score: float | None = None
    content: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ToolTraceCreate:
    trace_id: str
    tool_name: str
    arguments_json: Any = None
    result_json: Any = None
    status: str = "success"
    latency_ms: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EvalRecordUpsert:
    run_id: str
    case_id: str
    question: str
    expected_intent: str | None = None
    predicted_intent: str | None = None
    expected_doc_ids: Iterable[Any] | None = None
    retrieved_doc_ids: Iterable[Any] | None = None
    answer: str | None = None
    is_hit: bool | None = None
    error_type: str | None = None
    trace_id: str | None = None
    system_route: str | None = None
    eval_mode: str | None = None
    created_at: datetime | None = None


class RepositoryError(ValueError):
    """Raised when persistence input is invalid before hitting the database."""


class BaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _flush(self) -> None:
        self.session.flush()


class TraceRepository(BaseRepository):
    def create_agent_trace(self, data: AgentTraceCreate | Mapping[str, Any]) -> AgentTrace:
        item = _as_agent_trace_create(data)
        values: dict[str, Any] = dict(
            id=_required_str("id", item.id, max_len=64),
            sender_id=_required_str("sender_id", item.sender_id, max_len=128),
            conversation_id=_optional_str("conversation_id", item.conversation_id, max_len=128),
            user_text=_required_str("user_text", item.user_text),
            rewritten_query=_optional_str("rewritten_query", item.rewritten_query),
            intent_id=_optional_str("intent_id", item.intent_id, max_len=128),
            intent_confidence=item.intent_confidence,
            route=_optional_str("route", item.route, max_len=64),
            final_answer=_optional_str("final_answer", item.final_answer),
            latency_ms=_optional_int("latency_ms", item.latency_ms),
        )
        if item.created_at is not None:
            values["created_at"] = item.created_at
        trace = AgentTrace(**values)
        self.session.add(trace)
        self._flush()
        return trace

    def update_agent_trace(self, trace_id: str, **fields: Any) -> AgentTrace | None:
        trace = self.session.get(AgentTrace, _required_str("trace_id", trace_id, max_len=64))
        if trace is None:
            return None

        allowed = {
            "conversation_id",
            "rewritten_query",
            "intent_id",
            "intent_confidence",
            "route",
            "final_answer",
            "latency_ms",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise RepositoryError(f"Unsupported agent_trace update fields: {sorted(unknown)}")

        if "conversation_id" in fields:
            trace.conversation_id = _optional_str("conversation_id", fields["conversation_id"], max_len=128)
        if "rewritten_query" in fields:
            trace.rewritten_query = _optional_str("rewritten_query", fields["rewritten_query"])
        if "intent_id" in fields:
            trace.intent_id = _optional_str("intent_id", fields["intent_id"], max_len=128)
        if "intent_confidence" in fields:
            trace.intent_confidence = _optional_float("intent_confidence", fields["intent_confidence"])
        if "route" in fields:
            trace.route = _optional_str("route", fields["route"], max_len=64)
        if "final_answer" in fields:
            trace.final_answer = _optional_str("final_answer", fields["final_answer"])
        if "latency_ms" in fields:
            trace.latency_ms = _optional_int("latency_ms", fields["latency_ms"])

        self._flush()
        return trace

    def add_retrieval_traces(
        self,
        trace_id: str,
        records: Iterable[RetrievalTraceCreate | Mapping[str, Any]],
    ) -> list[RetrievalTrace]:
        tid = _required_str("trace_id", trace_id, max_len=64)
        traces: list[RetrievalTrace] = []
        for record in records:
            item = _as_retrieval_trace_create(record)
            values = dict(
                trace_id=tid,
                query=_required_str("query", item.query),
                channel=_required_str("channel", item.channel, max_len=32),
                doc_id=_optional_str("doc_id", item.doc_id, max_len=128),
                chunk_id=_optional_str("chunk_id", item.chunk_id, max_len=128),
                score=_optional_float("score", item.score),
                rerank_score=_optional_float("rerank_score", item.rerank_score),
                content=_optional_str("content", item.content),
            )
            if item.created_at is not None:
                values["created_at"] = item.created_at
            traces.append(RetrievalTrace(**values))

        if traces:
            self.session.add_all(traces)
            self._flush()
        return traces

    def add_tool_trace(self, data: ToolTraceCreate | Mapping[str, Any]) -> ToolTrace:
        item = _as_tool_trace_create(data)
        status = _required_str("status", item.status, max_len=32)
        _validate_choice("status", status, TOOL_STATUSES)
        values: dict[str, Any] = dict(
            trace_id=_required_str("trace_id", item.trace_id, max_len=64),
            tool_name=_required_str("tool_name", item.tool_name, max_len=128),
            arguments_json=_json_safe(item.arguments_json),
            result_json=_json_safe(item.result_json),
            status=status,
            latency_ms=_optional_int("latency_ms", item.latency_ms),
        )
        if item.created_at is not None:
            values["created_at"] = item.created_at
        trace = ToolTrace(**values)
        self.session.add(trace)
        self._flush()
        return trace


class EvalRepository(BaseRepository):
    def save_eval_record(self, data: EvalRecordUpsert | Mapping[str, Any]) -> EvalRecord:
        item = _as_eval_record_upsert(data)
        run_id = _required_str("run_id", item.run_id, max_len=128)
        case_id = _required_str("case_id", item.case_id, max_len=128)
        error_type = _optional_str("error_type", item.error_type, max_len=64)
        if error_type:
            _validate_choice("error_type", error_type, EVAL_ERROR_TYPES)

        record = self.session.execute(
            select(EvalRecord).where(EvalRecord.run_id == run_id, EvalRecord.case_id == case_id)
        ).scalar_one_or_none()

        values = {
            "run_id": run_id,
            "case_id": case_id,
            "question": _required_str("question", item.question),
            "expected_intent": _optional_str("expected_intent", item.expected_intent, max_len=128),
            "predicted_intent": _optional_str("predicted_intent", item.predicted_intent, max_len=128),
            "expected_doc_ids": _normalize_str_list("expected_doc_ids", item.expected_doc_ids),
            "retrieved_doc_ids": _normalize_str_list("retrieved_doc_ids", item.retrieved_doc_ids),
            "answer": _optional_str("answer", item.answer),
            "is_hit": item.is_hit,
            "error_type": error_type,
            "trace_id": _optional_str("trace_id", item.trace_id, max_len=64),
            "system_route": _optional_str("system_route", item.system_route, max_len=64),
            "eval_mode": _optional_str("eval_mode", item.eval_mode, max_len=32),
        }

        if record is None:
            if item.created_at is not None:
                values["created_at"] = item.created_at
            record = EvalRecord(**values)
            self.session.add(record)
        else:
            for key, value in values.items():
                setattr(record, key, value)

        self._flush()
        return record

    def list_badcases(
        self,
        *,
        run_id: str | None = None,
        error_type: str | None = None,
        limit: int = 100,
    ) -> list[EvalRecord]:
        if limit <= 0:
            raise RepositoryError("limit must be positive")

        stmt = select(EvalRecord).where(or_(EvalRecord.is_hit.is_(False), EvalRecord.error_type.is_not(None)))
        if run_id:
            stmt = stmt.where(EvalRecord.run_id == _required_str("run_id", run_id, max_len=128))
        if error_type:
            et = _required_str("error_type", error_type, max_len=64)
            _validate_choice("error_type", et, EVAL_ERROR_TYPES)
            stmt = stmt.where(EvalRecord.error_type == et)

        stmt = stmt.order_by(EvalRecord.created_at.desc(), EvalRecord.id.desc()).limit(limit)
        return list(self.session.execute(stmt).scalars().all())


def _as_agent_trace_create(data: AgentTraceCreate | Mapping[str, Any]) -> AgentTraceCreate:
    if isinstance(data, AgentTraceCreate):
        return data
    return AgentTraceCreate(**dict(data))


def _as_retrieval_trace_create(data: RetrievalTraceCreate | Mapping[str, Any]) -> RetrievalTraceCreate:
    if isinstance(data, RetrievalTraceCreate):
        return data
    return RetrievalTraceCreate(**dict(data))


def _as_tool_trace_create(data: ToolTraceCreate | Mapping[str, Any]) -> ToolTraceCreate:
    if isinstance(data, ToolTraceCreate):
        return data
    return ToolTraceCreate(**dict(data))


def _as_eval_record_upsert(data: EvalRecordUpsert | Mapping[str, Any]) -> EvalRecordUpsert:
    if isinstance(data, EvalRecordUpsert):
        return data
    return EvalRecordUpsert(**dict(data))


def _required_str(name: str, value: Any, *, max_len: int | None = None) -> str:
    if value is None:
        raise RepositoryError(f"{name} is required")
    text = str(value).strip()
    if not text:
        raise RepositoryError(f"{name} must not be empty")
    if max_len is not None and len(text) > max_len:
        raise RepositoryError(f"{name} exceeds max length {max_len}")
    return text


def _optional_str(name: str, value: Any, *, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value)
    if max_len is not None and len(text) > max_len:
        raise RepositoryError(f"{name} exceeds max length {max_len}")
    return text


def _optional_int(name: str, value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RepositoryError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise RepositoryError(f"{name} must not be negative")
    return parsed


def _optional_float(name: str, value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RepositoryError(f"{name} must be a number") from exc


def _validate_choice(name: str, value: str, choices: set[str]) -> None:
    if value not in choices:
        raise RepositoryError(f"{name} must be one of {sorted(choices)}")


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _normalize_str_list(name: str, values: Iterable[Any] | None) -> list[str] | None:
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise RepositoryError(f"{name} must be a list, not a string")
    result = [str(value).strip() for value in values if str(value).strip()]
    return result
