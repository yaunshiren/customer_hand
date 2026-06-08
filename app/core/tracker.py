from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.memory import DEFAULT_RECENT_TURN_LIMIT, ConversationMemory


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DialogueStateTracker:
    def __init__(self, sender_id: str, *, memory_turn_limit: int = DEFAULT_RECENT_TURN_LIMIT):
        timestamp = now_iso()
        self.sender_id = sender_id
        self.memory = ConversationMemory(recent_turn_limit=memory_turn_limit)
        self.slots: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self.latest_message: str | None = None
        self.latest_bot_message: str | None = None
        self.active_flow: str | None = None
        self.flow_status: str = "idle"
        self.flow_step_index: int = 0
        self.slot_to_collect: str | None = None
        self.flow_history: list[dict[str, Any]] = []
        self.latest_action_name: str | None = None
        self.created_at = timestamp
        self.updated_at = timestamp

    def update_with_user_message(self, message: str) -> None:
        timestamp = now_iso()
        self.latest_message = message
        self.updated_at = timestamp
        self.memory.start_user_turn(message, timestamp=timestamp)
        self.events.append(
            {
                "event": "user",
                "text": message,
                "timestamp": timestamp,
            }
        )

    def add_bot_message(self, text: str) -> None:
        timestamp = now_iso()
        self.latest_bot_message = text
        self.updated_at = timestamp
        self.memory.add_assistant_message(text, timestamp=timestamp)
        self.events.append(
            {
                "event": "bot",
                "text": text,
                "timestamp": timestamp,
            }
        )

    def set_slot(self, key: str, value: Any) -> None:
        timestamp = now_iso()
        self.slots[key] = value
        self.updated_at = timestamp
        if key in {"product", "order_id", "intent"}:
            self.memory.update_entities({key: value})
        self.events.append(
            {
                "event": "slot",
                "key": key,
                "value": value,
                "timestamp": timestamp,
            }
        )

    def get_slot(self, key: str, default: Any = None) -> Any:
        return self.slots.get(key, default)

    def get_all_slots(self) -> dict[str, Any]:
        return dict(self.slots)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sender_id": self.sender_id,
            "memory": self.memory.to_dict(),
            "slots": dict(self.slots),
            "events": list(self.events),
            "latest_message": self.latest_message,
            "latest_bot_message": self.latest_bot_message,
            "active_flow": self.active_flow,
            "flow_status": self.flow_status,
            "flow_step_index": self.flow_step_index,
            "slot_to_collect": self.slot_to_collect,
            "flow_history": list(self.flow_history),
            "latest_action_name": self.latest_action_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        memory_turn_limit: int = DEFAULT_RECENT_TURN_LIMIT,
    ) -> "DialogueStateTracker":
        tracker = cls(sender_id=str(data.get("sender_id", "default")), memory_turn_limit=memory_turn_limit)
        tracker.slots = dict(data.get("slots") or {})
        tracker.events = list(data.get("events") or [])
        if isinstance(data.get("memory"), dict):
            tracker.memory = ConversationMemory.from_dict(data.get("memory"), recent_turn_limit=memory_turn_limit)
        else:
            tracker.memory = ConversationMemory.from_events(tracker.events, recent_turn_limit=memory_turn_limit)
        tracker.latest_message = data.get("latest_message")
        tracker.latest_bot_message = data.get("latest_bot_message")
        tracker.active_flow = data.get("active_flow")
        tracker.flow_status = str(data.get("flow_status") or "idle")
        tracker.flow_step_index = int(data.get("flow_step_index") or 0)
        tracker.slot_to_collect = data.get("slot_to_collect")
        tracker.flow_history = list(data.get("flow_history") or [])
        tracker.latest_action_name = data.get("latest_action_name")
        tracker.created_at = data.get("created_at") or tracker.created_at
        tracker.updated_at = data.get("updated_at") or tracker.updated_at
        return tracker
