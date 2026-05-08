from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DialogueStateTracker:
    def __init__(self, sender_id: str):
        timestamp = now_iso()
        self.sender_id = sender_id
        self.slots: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self.latest_message: str | None = None
        self.latest_bot_message: str | None = None
        self.active_flow: str | None = None
        self.created_at = timestamp
        self.updated_at = timestamp

    def update_with_user_message(self, message: str) -> None:
        timestamp = now_iso()
        self.latest_message = message
        self.updated_at = timestamp
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
            "slots": dict(self.slots),
            "events": list(self.events),
            "latest_message": self.latest_message,
            "latest_bot_message": self.latest_bot_message,
            "active_flow": self.active_flow,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DialogueStateTracker":
        tracker = cls(sender_id=str(data.get("sender_id", "default")))
        tracker.slots = dict(data.get("slots") or {})
        tracker.events = list(data.get("events") or [])
        tracker.latest_message = data.get("latest_message")
        tracker.latest_bot_message = data.get("latest_bot_message")
        tracker.active_flow = data.get("active_flow")
        tracker.created_at = data.get("created_at") or tracker.created_at
        tracker.updated_at = data.get("updated_at") or tracker.updated_at
        return tracker
