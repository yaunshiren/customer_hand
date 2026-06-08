from __future__ import annotations

from app.agent.graph.nodes import generate_response, load_context
from app.core.tracker import DialogueStateTracker
from app.core.tracker_store import InMemoryTrackerStore
from app.memory import ConversationMemory


def test_conversation_memory_default_contract() -> None:
    memory = ConversationMemory()

    assert memory.to_dict() == {
        "recent_turns": [],
        "memory_entities": {
            "product": "",
            "order_id": "",
            "intent": "",
        },
        "summary": "",
    }


def test_tracker_memory_keeps_recent_n_turns() -> None:
    tracker = DialogueStateTracker("memory_user", memory_turn_limit=2)

    tracker.update_with_user_message("turn 1 user")
    tracker.add_bot_message("turn 1 assistant")
    tracker.update_with_user_message("turn 2 user")
    tracker.add_bot_message("turn 2 assistant")
    tracker.update_with_user_message("turn 3 user")
    tracker.add_bot_message("turn 3 assistant")

    snapshot = tracker.memory.to_dict()
    assert [turn["user"] for turn in snapshot["recent_turns"]] == ["turn 2 user", "turn 3 user"]
    assert [turn["assistant"] for turn in snapshot["recent_turns"]] == ["turn 2 assistant", "turn 3 assistant"]
    assert snapshot["summary"] == ""


def test_tracker_memory_entities_use_defined_shape() -> None:
    tracker = DialogueStateTracker("memory_entity_user")

    tracker.set_slot("order_id", "A10001")
    tracker.memory.update_entities({"product": "XPhone Pro", "intent": "warranty"})

    assert tracker.memory.to_dict()["memory_entities"] == {
        "product": "XPhone Pro",
        "order_id": "A10001",
        "intent": "warranty",
    }


def test_tracker_from_dict_restores_memory_from_legacy_events() -> None:
    tracker = DialogueStateTracker.from_dict(
        {
            "sender_id": "legacy_memory_user",
            "events": [
                {"event": "user", "text": "legacy user", "timestamp": "2026-06-08T00:00:00Z"},
                {"event": "bot", "text": "legacy assistant", "timestamp": "2026-06-08T00:00:01Z"},
                {"event": "slot", "key": "order_id", "value": "B20002", "timestamp": "2026-06-08T00:00:02Z"},
            ],
        }
    )

    snapshot = tracker.memory.to_dict()
    assert snapshot["recent_turns"][0]["user"] == "legacy user"
    assert snapshot["recent_turns"][0]["assistant"] == "legacy assistant"
    assert snapshot["memory_entities"]["order_id"] == "B20002"


def test_store_tracker_preserves_memory_after_serialized_restore() -> None:
    store = InMemoryTrackerStore(memory_turn_limit=2)
    tracker = store.get_or_create("serialized_memory_user")
    tracker.update_with_user_message("hello")
    tracker.add_bot_message("hi")
    store.save(tracker)

    store._data["serialized_memory_user"] = tracker.to_dict()
    restored = store.retrieve("serialized_memory_user")

    assert restored is not None
    assert restored.memory.to_dict()["recent_turns"][0]["assistant"] == "hi"


def test_generate_response_exposes_memory_snapshot_metadata() -> None:
    state = load_context(
        {
            "sender_id": "memory_response_user",
            "message": "Where is order A10001?",
            "tracker": DialogueStateTracker("memory_response_user"),
        }
    )
    tracker = state["tracker"]
    tracker.set_slot("order_id", "A10001")

    result = generate_response(
        {
            **state,
            "route": "chitchat",
            "reply_text": "It is on the way.",
            "business_classification": {
                "question_type": "order_query",
                "extracted_arguments": {"order_id": "A10001"},
            },
        }
    )

    metadata = result["responses"][0]["metadata"]
    snapshot = metadata["memory_snapshot"]
    assert snapshot["recent_turns"][-1]["user"] == "Where is order A10001?"
    assert snapshot["recent_turns"][-1]["assistant"] == "It is on the way."
    assert metadata["memory_entities"] == {
        "product": "",
        "order_id": "A10001",
        "intent": "order_query",
    }
