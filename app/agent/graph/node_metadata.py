from __future__ import annotations

from typing import Any

from app.agent.graph.state import AgentState
from app.agent.graph.node_services import _build_memory_entity_extractor
from app.agent.graph.node_shared import _model_dump
from app.rag.citation import CitationBuilder


def _intent_response_metadata(intent_result: Any, route_decision: Any) -> dict[str, Any]:
    intent_data = _model_dump(intent_result)
    decision_data = _model_dump(route_decision)

    metadata: dict[str, Any] = {}
    intent_id = str(intent_data.get("intent_id") or "").strip()
    if intent_id and intent_id != "UNKNOWN":
        metadata["intentLeafIds"] = [intent_id]
    elif intent_data:
        metadata["intentLeafIds"] = []

    if intent_data:
        metadata["intentSource"] = intent_data.get("source") or "unknown"
        metadata["intentConfidence"] = intent_data.get("confidence")
        metadata["intentKind"] = intent_data.get("intent_kind")
        metadata["intentRoute"] = intent_data.get("route")
        metadata["intentCandidates"] = intent_data.get("candidates") or []
        metadata["needsClarification"] = bool(intent_data.get("needs_clarification"))
        metadata["clarifyReason"] = intent_data.get("clarify_reason")

    if decision_data:
        metadata["execution_route"] = decision_data.get("execution_route")
        metadata["system_route"] = decision_data.get("system_route")
        metadata["route_reason"] = decision_data.get("reason")
        metadata["requires_rag"] = decision_data.get("requires_rag")

    return metadata


def _business_response_metadata(classification: Any) -> dict[str, Any]:
    data = _model_dump(classification)
    if not data:
        return {}

    return {
        "business_question_type": data.get("question_type"),
        "business_route": data.get("route"),
        "business_tool": data.get("target_tool"),
        "business_confidence": data.get("confidence"),
        "business_required_arguments": data.get("required_arguments") or [],
        "business_missing_arguments": data.get("missing_arguments") or [],
        "business_extracted_arguments": data.get("extracted_arguments") or {},
        "business_requires_rag": data.get("requires_rag"),
        "business_requires_confirmation": data.get("requires_confirmation"),
        "business_risk_level": data.get("risk_level"),
        "business_reason": data.get("reason"),
        "business_signals": data.get("signals") or [],
        "business_source": data.get("source"),
    }


def _tool_response_metadata(tool_result: Any) -> dict[str, Any]:
    data = _model_dump(tool_result)
    if not data:
        return {}

    error = data.get("error")
    error_code = error.get("code") if isinstance(error, dict) else None
    result_metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return {
        "tool_name": data.get("tool_name"),
        "tool_success": data.get("success"),
        "tool_status": data.get("status"),
        "tool_arguments": data.get("arguments") or {},
        "tool_error_code": error_code,
        "tool_latency_ms": data.get("latency_ms"),
        "tool_attempt_count": result_metadata.get("attempt_count"),
        "tool_timeout_seconds": result_metadata.get("timeout_seconds"),
    }


def _tool_safety_response_metadata(tool_safety: Any) -> dict[str, Any]:
    data = _model_dump(tool_safety)
    if not data:
        return {}

    return {
        "tool_safety_decision": data.get("decision"),
        "tool_safety_reason": data.get("reason"),
        "pending_tool_name": data.get("tool_name"),
        "pending_tool_arguments": data.get("arguments") or {},
    }


def _entry_response_metadata(state: AgentState) -> dict[str, Any]:
    if "entry_task" not in state:
        return {}

    security_flags = state.get("security_flags")
    return {
        "entry_source": state.get("source"),
        "entry_scenario": state.get("scenario"),
        "entry_capability": state.get("capability"),
        "tenant_id": state.get("tenant_id"),
        "roles": state.get("roles") or [],
        "security_flags": security_flags if isinstance(security_flags, dict) else {},
        "text_hash": (security_flags or {}).get("text_hash") if isinstance(security_flags, dict) else None,
    }


def _rag_response_metadata(
    *,
    route_name: str,
    original_query: str | None,
    rewritten_query: str | None,
    query_rewrite: dict[str, Any] | None,
    rag_matches: list[dict[str, Any]],
    used_llm: bool,
    ticket: dict[str, Any],
) -> dict[str, Any]:
    citation_metadata = CitationBuilder().from_matches(rag_matches)

    metadata = {
        "route": route_name,
        "rag_match_count": len(rag_matches),
        "used_llm": used_llm,
        "ticket_id": ticket.get("ticket_id") if isinstance(ticket, dict) else None,
        **citation_metadata,
    }
    if original_query:
        metadata["original_query"] = original_query
    if rewritten_query:
        metadata["rewritten_query"] = rewritten_query
    if query_rewrite:
        metadata["query_rewrite"] = dict(query_rewrite)
    return metadata


def _memory_response_metadata(state: AgentState, *, assistant_text: str = "") -> dict[str, Any]:
    tracker = state.get("tracker")
    memory = getattr(tracker, "memory", None)
    if memory is None or not hasattr(memory, "to_dict"):
        return {}

    extraction = _build_memory_entity_extractor(state).update_memory(
        memory,
        user_text=str(state.get("message") or ""),
        assistant_text=assistant_text,
        tracker=tracker,
        intent_result=state.get("intent_result"),
        business_classification=state.get("business_classification"),
    )
    snapshot = memory.to_dict()
    return {
        "memory_snapshot": snapshot,
        "memory_entities": dict(snapshot.get("memory_entities") or {}),
        "memory_extraction": extraction.to_dict(),
    }


def _merge_response_metadata(responses: list[dict[str, Any]], common: dict[str, Any]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for response in responses:
        item = dict(response)
        metadata = dict(item.get("metadata") or {})
        item["metadata"] = {**metadata, **common}
        merged.append(item)
    return merged
