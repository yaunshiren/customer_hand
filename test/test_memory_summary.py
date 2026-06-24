from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.memory.summary import MemorySummaryService
from app.settings import settings


def _message(message_id: int, role: str, content: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        role=role,
        content=content or f"{role} message {message_id}",
    )


def _conversation(turns: int) -> list[SimpleNamespace]:
    messages: list[SimpleNamespace] = []
    message_id = 1
    for turn in range(1, turns + 1):
        messages.append(_message(message_id, "user", f"user turn {turn}"))
        message_id += 1
        messages.append(_message(message_id, "assistant", f"assistant turn {turn}"))
        message_id += 1
    return messages


class FakeMemoryStore:
    def __init__(self, *, messages: list[SimpleNamespace], summary: SimpleNamespace | None = None) -> None:
        self.messages = messages
        self.summary = summary
        self.created_summaries: list[dict[str, Any]] = []

    def count_user_messages(self, *, sender_id: str, conversation_id: str | None = None) -> int:
        return sum(1 for item in self.messages if item.role == "user")

    def load_latest_user_messages(
        self,
        *,
        sender_id: str,
        conversation_id: str | None = None,
        limit: int,
    ) -> list[SimpleNamespace]:
        users = [item for item in self.messages if item.role == "user"]
        return list(reversed(users))[:limit]

    def find_latest_summary(self, *, sender_id: str, conversation_id: str | None = None) -> SimpleNamespace | None:
        return self.summary

    def list_messages_between(
        self,
        *,
        sender_id: str,
        conversation_id: str | None = None,
        after_id: int = 0,
        before_id: int | None = None,
    ) -> list[SimpleNamespace]:
        return [
            item
            for item in self.messages
            if item.id > after_id and (before_id is None or item.id < before_id)
        ]

    def create_summary(
        self,
        *,
        sender_id: str,
        last_message_id: int,
        content: str,
        conversation_id: str | None = None,
    ) -> SimpleNamespace:
        record = {
            "sender_id": sender_id,
            "conversation_id": conversation_id,
            "last_message_id": last_message_id,
            "content": content,
        }
        self.created_summaries.append(record)
        return SimpleNamespace(**record)


class FakeLLMClient:
    enabled = True

    def __init__(self, raw_output: str = '{"summary":"compressed memory"}', *, success: bool = True) -> None:
        self.raw_output = raw_output
        self.success = success
        self.calls: list[dict[str, Any]] = []

    def generate_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "success": self.success,
            "raw_output": self.raw_output,
            "usage": {},
            "latency_ms": 1,
            "model": "fake",
            "error": None if self.success else "fake failure",
        }


def _patch_memory_settings(
    monkeypatch: Any,
    *,
    recent_turn_limit: int = 2,
    start_turns: int = 4,
    batch_turns: int = 2,
    enabled: bool = True,
) -> None:
    monkeypatch.setattr(settings, "memory_summary_enabled", enabled)
    monkeypatch.setattr(settings, "memory_recent_turn_limit", recent_turn_limit)
    monkeypatch.setattr(settings, "memory_summary_start_turns", start_turns)
    monkeypatch.setattr(settings, "memory_summary_batch_turns", batch_turns)
    monkeypatch.setattr(settings, "memory_summary_max_chars", 1200)


def test_summary_skips_when_disabled(monkeypatch: Any) -> None:
    _patch_memory_settings(monkeypatch, enabled=False)
    store = FakeMemoryStore(messages=_conversation(5))
    llm = FakeLLMClient()
    service = MemorySummaryService(store=store, llm_client=llm)  # type: ignore[arg-type]

    assert service.compress_if_needed(sender_id="u1", conversation_id="c1") is False
    assert llm.calls == []
    assert store.created_summaries == []


def test_summary_skips_before_start_turn_threshold(monkeypatch: Any) -> None:
    _patch_memory_settings(monkeypatch, recent_turn_limit=2, start_turns=5, batch_turns=2)
    store = FakeMemoryStore(messages=_conversation(4))
    llm = FakeLLMClient()
    service = MemorySummaryService(store=store, llm_client=llm)  # type: ignore[arg-type]

    assert service.compress_if_needed(sender_id="u1", conversation_id="c1") is False
    assert llm.calls == []
    assert store.created_summaries == []


def test_summary_skips_until_stale_batch_reaches_threshold(monkeypatch: Any) -> None:
    _patch_memory_settings(monkeypatch, recent_turn_limit=2, start_turns=4, batch_turns=3)
    store = FakeMemoryStore(messages=_conversation(4))
    llm = FakeLLMClient()
    service = MemorySummaryService(store=store, llm_client=llm)  # type: ignore[arg-type]

    assert service.compress_if_needed(sender_id="u1", conversation_id="c1") is False
    assert llm.calls == []
    assert store.created_summaries == []


def test_summary_creates_record_when_stale_batch_reaches_threshold(monkeypatch: Any) -> None:
    _patch_memory_settings(monkeypatch, recent_turn_limit=2, start_turns=4, batch_turns=2)
    store = FakeMemoryStore(messages=_conversation(4))
    llm = FakeLLMClient()
    service = MemorySummaryService(store=store, llm_client=llm)  # type: ignore[arg-type]

    assert service.compress_if_needed(sender_id="u1", conversation_id="c1") is True

    assert len(llm.calls) == 1
    assert store.created_summaries == [
        {
            "sender_id": "u1",
            "conversation_id": "c1",
            "last_message_id": 4,
            "content": "compressed memory",
        }
    ]


def test_summary_uses_latest_summary_boundary(monkeypatch: Any) -> None:
    _patch_memory_settings(monkeypatch, recent_turn_limit=2, start_turns=5, batch_turns=1)
    latest_summary = SimpleNamespace(last_message_id=4, content="old compressed memory")
    store = FakeMemoryStore(messages=_conversation(5), summary=latest_summary)
    llm = FakeLLMClient('{"summary":"new compressed memory"}')
    service = MemorySummaryService(store=store, llm_client=llm)  # type: ignore[arg-type]

    assert service.compress_if_needed(sender_id="u1", conversation_id="c1") is True

    assert store.created_summaries[0]["last_message_id"] == 6
    user_prompt = llm.calls[0]["user_prompt"]
    assert "old compressed memory" in user_prompt
    assert "user turn 3" in user_prompt
    assert "user turn 1" not in user_prompt


def test_summary_does_not_create_record_for_invalid_llm_json(monkeypatch: Any) -> None:
    _patch_memory_settings(monkeypatch, recent_turn_limit=2, start_turns=4, batch_turns=2)
    store = FakeMemoryStore(messages=_conversation(4))
    llm = FakeLLMClient("not json")
    service = MemorySummaryService(store=store, llm_client=llm)  # type: ignore[arg-type]

    assert service.compress_if_needed(sender_id="u1", conversation_id="c1") is False
    assert len(llm.calls) == 1
    assert store.created_summaries == []
