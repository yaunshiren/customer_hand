from __future__ import annotations

from typing import Any

from app.core.tracker import DialogueStateTracker


class _StoreTracker(DialogueStateTracker):
    """Temporary dict-compatible tracker for the current Agent implementation."""

    def __init__(self, sender_id: str):
        super().__init__(sender_id)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if not hasattr(self, key):
            setattr(self, key, default)
        return getattr(self, key)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "_StoreTracker":
        tracker = cls(sender_id=str(data.get("sender_id", "default")))
        tracker.slots = dict(data.get("slots") or {})
        tracker.events = list(data.get("events") or [])
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


class InMemoryTrackerStore:
    def __init__(self):
        self._data: dict[str, DialogueStateTracker | dict[str, Any]] = {}

    def get_or_create(self, sender_id: str) -> DialogueStateTracker:
        tracker = self.retrieve(sender_id)
        if tracker is None:
            tracker = _StoreTracker(sender_id)
            self._data[sender_id] = tracker
        return tracker

    def save(self, tracker: DialogueStateTracker) -> None:
        sender_id = getattr(tracker, "sender_id", None)
        if not sender_id:
            raise ValueError("tracker.sender_id is required")
        self._data[sender_id] = tracker

    def retrieve(self, sender_id: str) -> DialogueStateTracker | None:
        tracker = self._data.get(sender_id)
        if tracker is None:
            return None

        if isinstance(tracker, dict):
            tracker = _StoreTracker.from_dict(tracker)
            self._data[sender_id] = tracker

        return tracker

    def delete(self, sender_id: str) -> bool:
        if sender_id not in self._data:
            return False

        del self._data[sender_id]
        return True
