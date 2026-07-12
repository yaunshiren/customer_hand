from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import delete, inspect

from app.memory.store import ConversationMemoryStore
from app.persistence.db import get_engine, ping_trace_db, trace_db_session
from app.persistence.models import ConversationMessage, ConversationSummary


pytestmark = [pytest.mark.integration, pytest.mark.mysql]


@pytest.fixture()
def memory_sender_id() -> Iterator[str]:
    try:
        ping_trace_db()
        inspector = inspect(get_engine())
        if not inspector.has_table("conversation_message") or not inspector.has_table("conversation_summary"):
            pytest.skip("conversation memory tables are not migrated")
    except Exception as exc:  # pragma: no cover - depends on local MySQL.
        pytest.skip(f"trace database is not available: {exc}")

    sender_id = f"memory_{uuid.uuid4().hex}"
    try:
        yield sender_id
    finally:
        with trace_db_session() as session:
            session.execute(delete(ConversationSummary).where(ConversationSummary.sender_id == sender_id))
            session.execute(delete(ConversationMessage).where(ConversationMessage.sender_id == sender_id))


def test_memory_store_persists_messages_and_summaries(memory_sender_id: str) -> None:
    store = ConversationMemoryStore()
    conversation_id = memory_sender_id

    first_user = store.append_message(
        sender_id=memory_sender_id,
        conversation_id=conversation_id,
        role="user",
        content="turn 1 user",
    )
    first_assistant = store.append_message(
        sender_id=memory_sender_id,
        conversation_id=conversation_id,
        role="assistant",
        content="turn 1 assistant",
    )
    second_user = store.append_message(
        sender_id=memory_sender_id,
        conversation_id=conversation_id,
        role="user",
        content="turn 2 user",
    )

    assert first_user.id < first_assistant.id < second_user.id
    assert store.count_user_messages(sender_id=memory_sender_id, conversation_id=conversation_id) == 2

    recent = store.load_recent_messages(sender_id=memory_sender_id, conversation_id=conversation_id, limit=2)
    assert [(item.role, item.content) for item in recent] == [
        ("assistant", "turn 1 assistant"),
        ("user", "turn 2 user"),
    ]

    latest_users = store.load_latest_user_messages(
        sender_id=memory_sender_id,
        conversation_id=conversation_id,
        limit=2,
    )
    assert [item.content for item in latest_users] == ["turn 2 user", "turn 1 user"]

    between = store.list_messages_between(
        sender_id=memory_sender_id,
        conversation_id=conversation_id,
        after_id=first_user.id,
        before_id=second_user.id,
    )
    assert [item.content for item in between] == ["turn 1 assistant"]

    store.create_summary(
        sender_id=memory_sender_id,
        conversation_id=conversation_id,
        last_message_id=first_assistant.id,
        content="first compressed summary",
    )
    latest = store.create_summary(
        sender_id=memory_sender_id,
        conversation_id=conversation_id,
        last_message_id=second_user.id,
        content="latest compressed summary",
    )

    loaded = store.find_latest_summary(sender_id=memory_sender_id, conversation_id=conversation_id)
    assert loaded is not None
    assert loaded.id == latest.id
    assert loaded.content == "latest compressed summary"


def test_memory_store_rejects_unknown_role(memory_sender_id: str) -> None:
    store = ConversationMemoryStore()

    with pytest.raises(ValueError):
        store.append_message(
            sender_id=memory_sender_id,
            conversation_id=memory_sender_id,
            role="system",
            content="not supported",
        )
