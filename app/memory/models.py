from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

DEFAULT_RECENT_TURN_LIMIT = 6
MAX_RECENT_TURN_LIMIT = 50
MAX_TEXT_CHARS = 4000
ENTITY_KEYS = ("product", "order_id", "intent")


def _clean_text(value: Any, *, max_chars: int = MAX_TEXT_CHARS) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _coerce_turn_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_RECENT_TURN_LIMIT
    return max(1, min(parsed, MAX_RECENT_TURN_LIMIT))


@dataclass(slots=True)
class MemoryEntities:
    product: str = ""
    order_id: str = ""
    intent: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "MemoryEntities":
        values = data if isinstance(data, dict) else {}
        return cls(
            product=_clean_text(values.get("product"), max_chars=256),
            order_id=_clean_text(values.get("order_id"), max_chars=128),
            intent=_clean_text(values.get("intent"), max_chars=128),
        )

    def update(self, values: dict[str, Any], *, allow_clear: bool = False) -> None:
        for key in ENTITY_KEYS:
            if key not in values:
                continue
            value = _clean_text(values.get(key), max_chars=256)
            if value or allow_clear:
                setattr(self, key, value)

    def to_dict(self) -> dict[str, str]:
        return {
            "product": self.product,
            "order_id": self.order_id,
            "intent": self.intent,
        }


@dataclass(slots=True)
class MemoryTurn:
    user: str = ""
    assistant: str = ""
    started_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "MemoryTurn":
        values = data if isinstance(data, dict) else {}
        started_at = _clean_text(values.get("started_at") or values.get("timestamp"), max_chars=64)
        updated_at = _clean_text(values.get("updated_at") or values.get("timestamp"), max_chars=64)
        return cls(
            user=_clean_text(values.get("user") or values.get("user_text")),
            assistant=_clean_text(values.get("assistant") or values.get("bot") or values.get("bot_text")),
            started_at=started_at,
            updated_at=updated_at or started_at,
        )

    def has_content(self) -> bool:
        return bool(self.user or self.assistant)

    def to_dict(self) -> dict[str, str]:
        return {
            "user": self.user,
            "assistant": self.assistant,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class ConversationMemory:
    recent_turn_limit: int = DEFAULT_RECENT_TURN_LIMIT
    recent_turns: list[MemoryTurn] = field(default_factory=list)
    memory_entities: MemoryEntities = field(default_factory=MemoryEntities)
    summary: str = ""

    def __post_init__(self) -> None:
        self.recent_turn_limit = _coerce_turn_limit(self.recent_turn_limit)
        self.recent_turns = [turn for turn in self.recent_turns if turn.has_content()]
        self._trim_recent_turns()

    @classmethod
    def from_dict(cls, data: Any, *, recent_turn_limit: int = DEFAULT_RECENT_TURN_LIMIT) -> "ConversationMemory":
        values = data if isinstance(data, dict) else {}
        limit = _coerce_turn_limit(values.get("recent_turn_limit") or recent_turn_limit)
        raw_turns = values.get("recent_turns")
        turns = [MemoryTurn.from_dict(item) for item in raw_turns] if isinstance(raw_turns, list) else []
        return cls(
            recent_turn_limit=limit,
            recent_turns=turns,
            memory_entities=MemoryEntities.from_dict(values.get("memory_entities")),
            summary=_clean_text(values.get("summary"), max_chars=MAX_TEXT_CHARS),
        )

    @classmethod
    def from_events(
        cls,
        events: Iterable[dict[str, Any]],
        *,
        recent_turn_limit: int = DEFAULT_RECENT_TURN_LIMIT,
    ) -> "ConversationMemory":
        memory = cls(recent_turn_limit=recent_turn_limit)
        for event in events:
            event_type = str(event.get("event") or "").strip()
            text = event.get("text")
            timestamp = _clean_text(event.get("timestamp"), max_chars=64)
            if event_type == "user":
                memory.start_user_turn(text, timestamp=timestamp)
            elif event_type == "bot":
                memory.add_assistant_message(text, timestamp=timestamp)
            elif event_type == "slot":
                key = str(event.get("key") or "").strip()
                if key in ENTITY_KEYS:
                    memory.update_entities({key: event.get("value")})
        return memory

    def start_user_turn(self, text: Any, *, timestamp: str = "") -> None:
        clean = _clean_text(text)
        if not clean:
            return
        ts = _clean_text(timestamp, max_chars=64)
        self.recent_turns.append(MemoryTurn(user=clean, started_at=ts, updated_at=ts))
        self._trim_recent_turns()

    def add_assistant_message(self, text: Any, *, timestamp: str = "") -> None:
        clean = _clean_text(text)
        if not clean:
            return
        ts = _clean_text(timestamp, max_chars=64)
        if self.recent_turns and not self.recent_turns[-1].assistant:
            self.recent_turns[-1].assistant = clean
            self.recent_turns[-1].updated_at = ts or self.recent_turns[-1].updated_at
        else:
            self.recent_turns.append(MemoryTurn(assistant=clean, started_at=ts, updated_at=ts))
        self._trim_recent_turns()

    def update_entities(self, values: dict[str, Any], *, allow_clear: bool = False) -> None:
        self.memory_entities.update(values, allow_clear=allow_clear)

    def set_summary(self, summary: Any) -> None:
        self.summary = _clean_text(summary, max_chars=MAX_TEXT_CHARS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recent_turns": [turn.to_dict() for turn in self.recent_turns],
            "memory_entities": self.memory_entities.to_dict(),
            "summary": self.summary,
        }

    def _trim_recent_turns(self) -> None:
        if len(self.recent_turns) > self.recent_turn_limit:
            self.recent_turns = self.recent_turns[-self.recent_turn_limit :]
