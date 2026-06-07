from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.persistence.db import trace_db_session
from app.persistence.models import AgentTrace, RetrievalTrace, ToolTrace
from app.persistence.repositories import EVAL_ERROR_TYPES, EvalRecordUpsert, EvalRepository


@dataclass(frozen=True, slots=True)
class EvalPersistSummary:
    run_id: str
    source_path: Path
    total: int
    saved: int
    badcases: int


def infer_run_id_from_path(path: str | Path) -> str:
    return Path(path).stem


def iter_eval_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    jsonl_path = Path(path)
    with jsonl_path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{jsonl_path}:{line_no} is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{jsonl_path}:{line_no} must be a JSON object")
            yield payload


def persist_eval_jsonl(path: str | Path, *, run_id: str | None = None) -> EvalPersistSummary:
    source_path = Path(path)
    actual_run_id = (run_id or infer_run_id_from_path(source_path)).strip()
    total = 0
    saved = 0
    badcases = 0

    with trace_db_session() as session:
        repo = EvalRepository(session)
        for index, raw in enumerate(iter_eval_jsonl(source_path), start=1):
            record = normalize_eval_record(raw, default_run_id=actual_run_id, case_index=index)
            record = enrich_eval_record_with_trace(record, session=session)
            repo.save_eval_record(record)
            total += 1
            saved += 1
            if record.is_hit is False or record.error_type:
                badcases += 1

    return EvalPersistSummary(
        run_id=actual_run_id,
        source_path=source_path,
        total=total,
        saved=saved,
        badcases=badcases,
    )


def normalize_eval_record(
    raw: Mapping[str, Any],
    *,
    default_run_id: str | None = None,
    case_index: int | None = None,
) -> EvalRecordUpsert:
    data = _nested_mapping(raw, "data")

    run_id = _as_optional_str(_pick(raw, ("run_id", "eval_run_id"))) or (default_run_id or "").strip()
    if not run_id:
        raise ValueError("run_id is required; pass default_run_id or include run_id in jsonl")

    case_id = (
        _as_optional_str(_pick(raw, ("case_id", "query_id", "id")))
        or _as_optional_str(_pick(data, ("case_id", "query_id", "id")))
        or (f"case_{case_index:04d}" if case_index is not None else "")
    )
    if not case_id:
        raise ValueError("case_id is required when case_index is not provided")

    question = (
        _as_optional_str(_pick(raw, ("question", "query", "user_input", "input")))
        or _as_optional_str(_pick(data, ("question", "query", "user_input", "input")))
        or ""
    )
    if not question.strip():
        raise ValueError(f"question is required for case_id={case_id}")

    expected_intent = _as_optional_str(_pick(raw, ("expected_intent", "intent_l2", "intent")))
    predicted_intent = (
        _as_optional_str(_pick(raw, ("predicted_intent", "intent_pred")))
        or _first_str(_pick(raw, ("intent_pred_all",)))
        or _first_str(_pick(data, ("intentLeafIds", "intent_pred_all")))
    )
    expected_doc_ids = _as_str_list(
        _pick(raw, ("expected_doc_ids", "reference_doc_ids", "expectedDocIds", "referenceDocIds"))
    )
    retrieved_doc_ids = _as_str_list(
        _pick(raw, ("retrieved_doc_ids", "retrievedDocIds", "rag_doc_ids"))
        if _pick(raw, ("retrieved_doc_ids", "retrievedDocIds", "rag_doc_ids")) is not None
        else _pick(data, ("retrieved_doc_ids", "retrievedDocIds", "rag_doc_ids"))
    )
    answer = (
        _as_optional_str(_pick(raw, ("answer", "response", "final_answer", "output")))
        or _as_optional_str(_pick(data, ("answer", "response", "final_answer", "output")))
    )
    trace_id = _as_optional_str(_pick(raw, ("trace_id", "traceId"))) or _as_optional_str(_pick(data, ("trace_id", "traceId")))
    system_route = (
        _as_optional_str(_pick(raw, ("system_route", "systemRoute", "route")))
        or _as_optional_str(_pick(data, ("system_route", "systemRoute", "route")))
    )
    eval_mode = _as_optional_str(_pick(raw, ("eval_mode", "evalMode")))

    explicit_hit = _parse_optional_bool(_pick(raw, ("is_hit", "isHit", "hit")))
    is_hit = explicit_hit if explicit_hit is not None else _infer_hit(
        expected_intent=expected_intent,
        predicted_intent=predicted_intent,
        expected_doc_ids=expected_doc_ids,
        retrieved_doc_ids=retrieved_doc_ids,
        raw=raw,
    )
    error_type = (
        _normalize_error_type(_pick(raw, ("error_type", "errorType")))
        or _error_type_from_reasons(_as_str_list(_pick(raw, ("reasons", "failure_reasons"))))
        or _infer_error_type(
            expected_intent=expected_intent,
            predicted_intent=predicted_intent,
            expected_doc_ids=expected_doc_ids,
            retrieved_doc_ids=retrieved_doc_ids,
            system_route=system_route,
            raw=raw,
        )
    )
    if error_type is None and is_hit is False:
        error_type = "GENERATION_HALLUCINATION"

    return EvalRecordUpsert(
        run_id=run_id,
        case_id=case_id,
        question=question,
        expected_intent=expected_intent,
        predicted_intent=predicted_intent,
        expected_doc_ids=expected_doc_ids,
        retrieved_doc_ids=retrieved_doc_ids,
        answer=answer,
        is_hit=is_hit,
        error_type=error_type,
        trace_id=trace_id,
        system_route=system_route,
        eval_mode=eval_mode,
    )


def enrich_eval_record_with_trace(record: EvalRecordUpsert, *, session: Any) -> EvalRecordUpsert:
    trace_error_type = _trace_error_type(record, session=session)
    if trace_error_type is None:
        return record

    if trace_error_type in {"TOOL_ARGUMENT_ERROR", "TOOL_FAILURE", "INTENT_ERROR", "ROUTE_ERROR"}:
        return replace(record, error_type=trace_error_type)
    if record.error_type is None:
        return replace(record, error_type=trace_error_type)
    return record


def _nested_mapping(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if isinstance(value, Mapping):
        return value
    return {}


def _pick(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_str(value: Any) -> str | None:
    values = _as_str_list(value)
    if not values:
        return None
    return values[0]


def _as_str_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in text.split(",") if item.strip()]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _parse_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "hit", "success"}:
        return True
    if text in {"0", "false", "no", "n", "miss", "failed", "failure"}:
        return False
    return None


def _infer_hit(
    *,
    expected_intent: str | None,
    predicted_intent: str | None,
    expected_doc_ids: list[str] | None,
    retrieved_doc_ids: list[str] | None,
    raw: Mapping[str, Any],
) -> bool | None:
    expected_docs = set(expected_doc_ids or [])
    retrieved_docs = set(retrieved_doc_ids or [])
    if expected_docs:
        return bool(expected_docs & retrieved_docs)
    if expected_intent and predicted_intent:
        return expected_intent == predicted_intent
    status = _as_optional_str(_pick(raw, ("final_status", "status")))
    if status and status.lower() in {"error", "refused", "cancelled", "failed"}:
        return False
    return None


def _normalize_error_type(value: Any) -> str | None:
    text = _as_optional_str(value)
    if not text:
        return None
    candidate = text.upper()
    if candidate in EVAL_ERROR_TYPES:
        return candidate
    return None


def _error_type_from_reasons(reasons: list[str] | None) -> str | None:
    text = " ".join(reasons or []).lower()
    if not text:
        return None
    if "intent" in text:
        return "INTENT_ERROR"
    if "route" in text:
        return "ROUTE_ERROR"
    if "argument" in text or "param" in text:
        return "TOOL_ARGUMENT_ERROR"
    if "rerank" in text or "rank" in text or "top1" in text:
        return "RERANK_ERROR"
    if "retrieval" in text or "recall" in text or "doc" in text or "context" in text:
        return "RETRIEVAL_MISS"
    if "tool" in text:
        return "TOOL_FAILURE"
    if "generation" in text or "hallucination" in text or "faithfulness" in text or "answer" in text:
        return "GENERATION_HALLUCINATION"
    return None


def _infer_error_type(
    *,
    expected_intent: str | None,
    predicted_intent: str | None,
    expected_doc_ids: list[str] | None,
    retrieved_doc_ids: list[str] | None,
    system_route: str | None,
    raw: Mapping[str, Any],
) -> str | None:
    if _pick(raw, ("tool_error", "tool_failure")):
        return "TOOL_FAILURE"
    if _pick(raw, ("tool_argument_error", "tool_param_error")):
        return "TOOL_ARGUMENT_ERROR"

    if expected_intent and predicted_intent and expected_intent != predicted_intent:
        return "INTENT_ERROR"

    expected_docs = set(expected_doc_ids or [])
    retrieved_docs = list(retrieved_doc_ids or [])
    if expected_docs:
        if system_route and system_route not in {"rag", "kb", "kb_tool", "kb_ticket"} and not retrieved_docs:
            return "ROUTE_ERROR"
        if not retrieved_docs or not (expected_docs & set(retrieved_docs)):
            return "RETRIEVAL_MISS"
        if retrieved_docs[0] not in expected_docs:
            return "RERANK_ERROR"

    status = _as_optional_str(_pick(raw, ("final_status", "status")))
    if status and status.lower() in {"error", "refused", "cancelled", "failed"}:
        if system_route and system_route in {"action", "tool", "ticket", "kb_tool", "kb_ticket"}:
            return "TOOL_FAILURE"
        return "GENERATION_HALLUCINATION"
    if _pick(raw, ("error", "exception")):
        if system_route and system_route in {"action", "tool", "ticket", "kb_tool", "kb_ticket"}:
            return "TOOL_FAILURE"
        return "GENERATION_HALLUCINATION"
    return None


def _trace_error_type(record: EvalRecordUpsert, *, session: Any) -> str | None:
    trace_id = _as_optional_str(record.trace_id)
    if not trace_id:
        return None

    failed_tool = session.execute(
        select(ToolTrace).where(ToolTrace.trace_id == trace_id, ToolTrace.status == "failed").order_by(ToolTrace.id.asc())
    ).scalars().first()
    if failed_tool is not None:
        result = failed_tool.result_json if isinstance(failed_tool.result_json, dict) else {}
        failure_type = _normalize_error_type(result.get("failure_type")) if result else None
        if failure_type in {"TOOL_ARGUMENT_ERROR", "TOOL_FAILURE"}:
            return failure_type
        error_text = f"{result.get('error_type') or ''} {result.get('error') or ''}".lower()
        if "argument" in error_text or "param" in error_text:
            return "TOOL_ARGUMENT_ERROR"
        return "TOOL_FAILURE"

    agent_trace = session.get(AgentTrace, trace_id)
    if agent_trace is not None:
        if record.expected_intent and agent_trace.intent_id and record.expected_intent != agent_trace.intent_id:
            return "INTENT_ERROR"
        if (
            record.expected_doc_ids
            and not record.retrieved_doc_ids
            and agent_trace.route
            and agent_trace.route not in {"rag", "kb", "kb_tool", "kb_ticket"}
        ):
            return "ROUTE_ERROR"

    if record.expected_doc_ids and not record.retrieved_doc_ids:
        retrieval_count = session.execute(
            select(RetrievalTrace.id).where(RetrievalTrace.trace_id == trace_id).limit(1)
        ).first()
        if retrieval_count is None:
            return "RETRIEVAL_MISS"

    return None
