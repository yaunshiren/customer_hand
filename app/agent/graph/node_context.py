from __future__ import annotations

from app.agent.graph.state import AgentState
from app.agent.graph.node_services import _build_memory_entity_extractor
from app.agent.graph.node_tracker import _normalize_tracker


def load_context(state: AgentState) -> AgentState:
    sender_id = str(state.get("sender_id") or "default")
    conversation_id = str(state.get("conversation_id") or sender_id)
    message = str(state.get("message") or "").strip()
    tracker = _normalize_tracker(state.get("tracker"), sender_id)
    memory_service = state.get("memory_service")

    if memory_service is not None:
        tracker.memory = memory_service.load(
            sender_id=sender_id,
            conversation_id=conversation_id,
        )

    tracker.update_with_user_message(message)

    if memory_service is not None:
        memory_service.append_user(
            sender_id=sender_id,
            conversation_id=conversation_id,
            content=message,
        )

    memory_extraction = _build_memory_entity_extractor(state).update_memory(
        tracker.memory,
        user_text=message,
        tracker=tracker,
    )

    return {
        **state,
        "sender_id": sender_id,
        "conversation_id": conversation_id,
        "message": message,
        "tracker": tracker,
        "memory_extraction": memory_extraction.to_dict(),
    }


def save_context(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    tracker_store = state.get("tracker_store")

    if tracker_store is not None and tracker is not None:
        tracker_store.save(tracker)

    return {
        **state,
        "saved": True,
    }
