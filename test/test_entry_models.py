import pytest
from pydantic import ValidationError

from app.entry.models import EntryTask, Principal, SecurityFlags


def test_principal_defaults() -> None:
    principal = Principal()
    assert principal.user_id == "anonymous"
    assert principal.tenant_id == "default"
    assert principal.roles == ["anonymous"]
    assert principal.auth_type == "anonymous"


def test_entry_task_strips_required_text() -> None:
    task = EntryTask(
        trace_id=" trace-1 ",
        request_id=" req-1 ",
        sender_id=" user-1 ",
        conversation_id=" conv-1 ",
        raw_text=" hello ",
        normalized_text=" hello ",
    )

    assert task.trace_id == "trace-1"
    assert task.request_id == "req-1"
    assert task.sender_id == "user-1"
    assert task.conversation_id == "conv-1"
    assert task.normalized_text == "hello"
    assert task.source == "api"
    assert task.scenario == "chat"
    assert task.capability == "chat"
    assert isinstance(task.security_flags, SecurityFlags)


def test_entry_task_rejects_empty_normalized_text() -> None:
    with pytest.raises(ValidationError):
        EntryTask(
            trace_id="trace-1",
            request_id="req-1",
            sender_id="user-1",
            conversation_id="conv-1",
            raw_text="   ",
            normalized_text="   ",
        )