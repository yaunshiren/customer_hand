from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from app.agent.graph.nodes import generate_response, load_context
from app.core.tracker import DialogueStateTracker
from app.memory import ConversationMemory, ConversationMemoryService, MemoryEntityExtractor, ProductCatalog


def _message(message_id: int, role: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        role=role,
        content=content,
        created_at=datetime(2026, 6, 24, 10, message_id, tzinfo=timezone.utc),
    )


class FakeMemoryStore:
    def __init__(self) -> None:
        self.summary: SimpleNamespace | None = None
        self.messages: list[SimpleNamespace] = []
        self.appended: list[dict[str, Any]] = []

    def find_latest_summary(self, *, sender_id: str, conversation_id: str | None = None) -> SimpleNamespace | None:
        return self.summary

    def load_recent_messages(
        self,
        *,
        sender_id: str,
        conversation_id: str | None = None,
        limit: int,
    ) -> list[SimpleNamespace]:
        return self.messages[-limit:]

    def append_message(
        self,
        *,
        sender_id: str,
        role: str,
        content: str,
        conversation_id: str | None = None,
    ) -> SimpleNamespace:
        row = _message(len(self.appended) + 1, role, content)
        self.appended.append(
            {
                "sender_id": sender_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
            }
        )
        return row


class FakeSummaryService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def compress_if_needed(self, *, sender_id: str, conversation_id: str | None = None) -> bool:
        self.calls.append({"sender_id": sender_id, "conversation_id": conversation_id})
        return True


class FakeGraphMemoryService:
    def __init__(self) -> None:
        self.appended_users: list[dict[str, Any]] = []
        self.appended_assistants: list[dict[str, Any]] = []

    def load(self, *, sender_id: str, conversation_id: str | None = None) -> ConversationMemory:
        memory = ConversationMemory(recent_turn_limit=2)
        memory.set_summary("previous summary")
        memory.start_user_turn("previous question")
        memory.add_assistant_message("previous answer")
        return memory

    def append_user(self, **kwargs: Any) -> None:
        self.appended_users.append(dict(kwargs))

    def append_assistant(self, **kwargs: Any) -> None:
        self.appended_assistants.append(dict(kwargs))


def test_memory_service_loads_summary_and_recent_turns() -> None:
    store = FakeMemoryStore()
    store.summary = SimpleNamespace(content="user asked about order A10001 logistics")
    store.messages = [
        _message(1, "user", "turn 1 user"),
        _message(2, "assistant", "turn 1 assistant"),
        _message(3, "user", "turn 2 user"),
        _message(4, "assistant", "turn 2 assistant"),
    ]
    service = ConversationMemoryService(
        store=store,  # type: ignore[arg-type]
        recent_turn_limit=2,
        summary_service=FakeSummaryService(),  # type: ignore[arg-type]
    )

    memory = service.load(sender_id="u1", conversation_id="c1")

    snapshot = memory.to_dict()
    assert snapshot["summary"] == "user asked about order A10001 logistics"
    assert [turn["user"] for turn in snapshot["recent_turns"]] == ["turn 1 user", "turn 2 user"]
    assert [turn["assistant"] for turn in snapshot["recent_turns"]] == [
        "turn 1 assistant",
        "turn 2 assistant",
    ]


def test_memory_service_append_user_ignores_blank_content() -> None:
    store = FakeMemoryStore()
    service = ConversationMemoryService(
        store=store,  # type: ignore[arg-type]
        summary_service=FakeSummaryService(),  # type: ignore[arg-type]
    )

    assert service.append_user(sender_id="u1", conversation_id="c1", content="   ") is None
    assert store.appended == []


def test_memory_service_append_assistant_triggers_summary_check() -> None:
    store = FakeMemoryStore()
    summary_service = FakeSummaryService()
    service = ConversationMemoryService(
        store=store,  # type: ignore[arg-type]
        summary_service=summary_service,  # type: ignore[arg-type]
    )

    message = service.append_assistant(sender_id="u1", conversation_id="c1", content="assistant answer")

    assert message is not None
    assert store.appended == [
        {
            "sender_id": "u1",
            "conversation_id": "c1",
            "role": "assistant",
            "content": "assistant answer",
        }
    ]
    assert summary_service.calls == [{"sender_id": "u1", "conversation_id": "c1"}]


def test_load_context_restores_persisted_memory_and_appends_user_message() -> None:
    memory_service = FakeGraphMemoryService()

    state = load_context(
        {
            "sender_id": "u1",
            "conversation_id": "c1",
            "message": "current question",
            "tracker": DialogueStateTracker("u1"),
            "memory_service": memory_service,
            "memory_entity_extractor": MemoryEntityExtractor(ProductCatalog([])),
        }
    )

    tracker = state["tracker"]
    snapshot = tracker.memory.to_dict()
    assert snapshot["summary"] == "previous summary"
    assert [turn["user"] for turn in snapshot["recent_turns"]] == [
        "previous question",
        "current question",
    ]
    assert memory_service.appended_users == [
        {"sender_id": "u1", "conversation_id": "c1", "content": "current question"}
    ]


def test_generate_response_persists_assistant_message_after_final_text() -> None:
    memory_service = FakeGraphMemoryService()
    tracker = DialogueStateTracker("u1")
    tracker.update_with_user_message("current question")

    result = generate_response(
        {
            "sender_id": "u1",
            "conversation_id": "c1",
            "tracker": tracker,
            "memory_service": memory_service,
            "route": "chitchat",
            "reply_text": "current answer",
        }
    )

    assert result["responses"][0]["text"] == "current answer"
    assert memory_service.appended_assistants == [
        {"sender_id": "u1", "conversation_id": "c1", "content": "current answer"}
    ]
