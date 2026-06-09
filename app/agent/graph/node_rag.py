from __future__ import annotations

import logging
from typing import Any

from app.agent.graph.state import AgentState
from app.agent.graph.node_services import _build_query_rewriter
from app.agent.graph.node_shared import _first_command_data, _model_dump
from app.rag.answerer import KnowledgeAnswerer

logger = logging.getLogger(__name__)


def _query_rewrite_metadata(result: Any, *, original_query: str) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        data = result.to_dict()
        if isinstance(data, dict):
            return dict(data)
    if isinstance(result, dict):
        return dict(result)
    return {
        "original_query": original_query,
        "rewritten_query": original_query,
        "memory_entities": {},
        "rewrite_applied": False,
        "reason": "unsupported_rewrite_result",
    }


def rag(state: AgentState) -> AgentState:
    results = state.get("llm_results") or []
    message = str(state.get("message") or "").strip()
    tracker = state.get("tracker")
    knowledge_answerer = state.get("knowledge_answerer")

    if not isinstance(knowledge_answerer, KnowledgeAnswerer):
        knowledge_answerer = KnowledgeAnswerer()

    command_data = _first_command_data(results, "knowledge_answer")
    original_query = str(command_data.get("query") or message).strip()
    try:
        rewrite_result = _build_query_rewriter(state).rewrite(original_query, getattr(tracker, "memory", None))
        query_rewrite = _query_rewrite_metadata(rewrite_result, original_query=original_query)
    except Exception as exc:
        logger.exception("query rewrite failed: %s", exc)
        query_rewrite = {
            "original_query": original_query,
            "rewritten_query": original_query,
            "memory_entities": {},
            "rewrite_applied": False,
            "reason": "rewrite_error",
        }

    rag_query = str(query_rewrite.get("rewritten_query") or original_query).strip()
    top_k = int(command_data.get("top_k") or 3)
    intent_data = _model_dump(state.get("intent_result"))
    intent_id = str(intent_data.get("intent_id") or "").strip()
    if intent_id == "UNKNOWN":
        intent_id = ""

    try:
        answer = knowledge_answerer.answer(rag_query, top_k=top_k, intent_id=intent_id or None)
    except Exception as exc:
        logger.exception("rag node failed: %s", exc)
        return {
            **state,
            "error": str(exc),
            "route": "fallback",
            "rag_query": rag_query,
            "query_rewrite": query_rewrite,
            "rag_matches": [],
            "knowledge_answer": "",
            "used_llm": False,
        }

    return {
        **state,
        "rag_query": rag_query,
        "query_rewrite": query_rewrite,
        "rag_matches": answer.get("matches", []),
        "knowledge_answer": str(answer.get("answer") or ""),
        "used_llm": bool(answer.get("used_llm")),
    }
