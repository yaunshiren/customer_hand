from __future__ import annotations

from app.agent.graph.state import AgentState
from app.agent.graph.node_metadata import (
    _business_response_metadata,
    _entry_response_metadata,
    _intent_response_metadata,
    _memory_response_metadata,
    _merge_response_metadata,
    _rag_response_metadata,
    _tool_response_metadata,
    _tool_safety_response_metadata,
)


def generate_response(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    sender_id = str(state.get("sender_id") or "default")
    reply_text = str(state.get("reply_text") or "").strip()
    responses = list(state.get("responses") or [])
    action_result = state.get("action_result") or {}
    tool_result = state.get("tool_result") or {}
    ticket = state.get("ticket") or {}
    route_name = str(state.get("route") or "fallback")
    rag_matches = state.get("rag_matches") or []
    knowledge_answer = str(state.get("knowledge_answer") or "")
    error = str(state.get("error") or "")
    query_rewrite = state.get("query_rewrite") if isinstance(state.get("query_rewrite"), dict) else None
    common_metadata = _rag_response_metadata(
        route_name=route_name,
        original_query=str((query_rewrite or {}).get("original_query") or "").strip() or None,
        rewritten_query=str((query_rewrite or {}).get("rewritten_query") or state.get("rag_query") or "").strip() or None,
        query_rewrite=query_rewrite,
        rag_matches=rag_matches,
        used_llm=bool(state.get("used_llm")),
        ticket=ticket if isinstance(ticket, dict) else {},
    )
    common_metadata.update(_intent_response_metadata(state.get("intent_result"), state.get("route_decision")))
    common_metadata.update(_business_response_metadata(state.get("business_classification")))
    common_metadata.update(_tool_response_metadata(tool_result))
    common_metadata.update(_tool_safety_response_metadata(state.get("tool_safety")))
    common_metadata.update(_entry_response_metadata(state))

    if reply_text and route_name in {"chitchat", "clarify"}:
        responses = [
            {
                "recipient_id": sender_id,
                "text": reply_text,
                "metadata": {"source": "llm" if route_name == "chitchat" else "business_router", "command_type": route_name},
            }
        ]

    if tracker is not None and responses:
        final_text = str(responses[0].get("text") or "")
        tracker.add_bot_message(final_text)
        tracker.latest_action_name = str(
            action_result.get("metadata", {}).get("action")
            or tool_result.get("tool_name")
            or tracker.latest_action_name
            or route_name
        )

    final_responses = list(responses)
    if not final_responses:
        fallback_text = knowledge_answer or str(action_result.get("text") or "系统暂时不可用。")
        final_responses = [
            {
                "recipient_id": sender_id,
                "text": fallback_text,
                "metadata": {
                    "route": route_name,
                    "rag_match_count": len(rag_matches),
                    "error": error or None,
                    **(action_result.get("metadata") or {}),
                },
            }
        ]
        if tracker is not None:
            tracker.add_bot_message(fallback_text)

    assistant_text = str(final_responses[0].get("text") or "") if final_responses else ""

    memory_service = state.get("memory_service")
    conversation_id = str(state.get("conversation_id") or sender_id)

    if memory_service is not None and assistant_text:
        memory_service.append_assistant(
            sender_id=sender_id,
            conversation_id=conversation_id,
            content=assistant_text,
        )

    common_metadata.update(_memory_response_metadata(state, assistant_text=assistant_text))
    final_responses = _merge_response_metadata(final_responses, common_metadata)

    return {
        **state,
        "responses": final_responses,
    }
