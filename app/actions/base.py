from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.tracker import DialogueStateTracker


@dataclass
class ActionResult:
    text: str | None = None
    buttons: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_event(self, event_type: str, **kwargs: Any) -> None:
        event = {"event": event_type}
        event.update(kwargs)
        self.events.append(event)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "buttons": list(self.buttons),
            "events": list(self.events),
            "metadata": dict(self.metadata),
        }


class Action:
    name: str = ""

    def run(
        self,
        tracker: DialogueStateTracker,
        **kwargs: Any,
    ) -> ActionResult:
        raise NotImplementedError
