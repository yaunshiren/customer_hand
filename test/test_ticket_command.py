from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.tracker import DialogueStateTracker
from app.dialogue.command_parser import CommandParser
from app.dialogue.command_processor import CommandProcessor
from app.dialogue.commands import TicketCommand
from app.llm.prompts import PromptBuilder


def _combined_prompt(tracker: Any, user_message: str) -> str:
    system, user = PromptBuilder().build(tracker=tracker, user_message=user_message)
    return f"{system}\n\n{user}"


def test_prompt_mentions_ticket_rules() -> None:
    tracker = DialogueStateTracker("ticket_user")
    prompt = _combined_prompt(tracker, "我想人工处理这个问题")

    assert "ticket" in prompt
    assert "只有在明确需要人工介入时，才输出 ticket" in prompt
    assert "reason" in prompt


def test_parse_ticket_command() -> None:
    parser = CommandParser()

    commands = parser.parse('{"commands":[{"type":"ticket","text":"用户要人工","reason":"need_human","category":"complaint","priority":"high"}]}')

    assert len(commands) == 1
    assert isinstance(commands[0], TicketCommand)
    assert commands[0].text == "用户要人工"
    assert commands[0].reason == "need_human"
    assert commands[0].category == "complaint"
    assert commands[0].priority == "high"


def test_process_ticket_command_records_event() -> None:
    tracker = DialogueStateTracker("ticket_user_2")
    commands = [TicketCommand(text="用户需要人工", reason="need_human", category="complaint", priority="high")]

    results = CommandProcessor().process(tracker, commands)

    assert len(results) == 1
    assert results[0]["type"] == "ticket"
    assert results[0]["success"] is True
    assert results[0]["data"]["text"] == "用户需要人工"
    assert tracker.events
    assert any(event.get("command_type") == "ticket" for event in tracker.events)
