from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ActionResult:
    responses: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_response(self, text: str, **kwargs: Any) -> None:
        payload: dict[str, Any] = {"text": text}
        payload.update(kwargs)
        self.responses.append(payload)
    
    def add_event(self, event_type: str, **kwargs: Any) -> None:
        payload: dict[str, Any] = {"event": event_type}
        payload.update(kwargs)
        self.events.append(payload)