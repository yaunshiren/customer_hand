from __future__ import annotations

from datetime import datetime
from typing import Any

from app.memory.models import ConversationMemory
from app.memory.store import ConversationMemoryStore
from app.persistence.models import ConversationMessage
from app.settings import settings
from app.memory.summary import MemorySummaryService


class ConversationMemoryService:
    def __init__(
        self,
        *,
        store: ConversationMemoryStore | None = None,
        recent_turn_limit: int | None = None,
        summary_service: MemorySummaryService | None = None,
    ) -> None:
        self.store = store or ConversationMemoryStore()
        self.recent_turn_limit = recent_turn_limit or settings.memory_recent_turn_limit
        self.summary_service = summary_service or MemorySummaryService(store=self.store)

    def load(
        self,
        *,
        sender_id: str,
        conversation_id: str | None = None,
    ) -> ConversationMemory:
        memory = ConversationMemory(recent_turn_limit=self.recent_turn_limit)

        latest_summary = self.store.find_latest_summary(
            sender_id=sender_id,
            conversation_id=conversation_id,
        )
        if latest_summary is not None:
            memory.set_summary(latest_summary.content)

        messages = self.store.load_recent_messages(
            sender_id=sender_id,
            conversation_id=conversation_id,
            limit=self.recent_turn_limit * 2,
        )
        self._append_messages_to_memory(memory, messages)
        return memory

    def append_user(
        self,
        *,
        sender_id: str,
        content: str,
        conversation_id: str | None = None,
    ) -> ConversationMessage | None:
        text = self._clean_content(content)
        if not text:
            return None

        return self.store.append_message(
            sender_id=sender_id,
            conversation_id=conversation_id,
            role="user",
            content=text,
        )

    def append_assistant(
        self,
        *,
        sender_id: str,
        content: str,
        conversation_id: str | None = None,
    ) -> ConversationMessage | None:
        text = self._clean_content(content)
        if not text:
            return None

        message = self.store.append_message(
            sender_id=sender_id,
            conversation_id=conversation_id,
            role="assistant",
            content=text,
        )

        self.summary_service.compress_if_needed(
            sender_id=sender_id,
            conversation_id=conversation_id,
        )
        return message

    def _append_messages_to_memory(
        self,
        memory: ConversationMemory,
        messages: list[ConversationMessage],
    ) -> None:
        for message in messages:
            timestamp = self._timestamp(message.created_at)
            if message.role == "user":
                memory.start_user_turn(message.content, timestamp=timestamp)
            elif message.role == "assistant":
                memory.add_assistant_message(message.content, timestamp=timestamp)

    def _timestamp(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "")

    def _clean_content(self, value: str) -> str:
        return str(value or "").strip()