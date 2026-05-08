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
