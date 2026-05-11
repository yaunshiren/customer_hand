from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.dialogue.command_parser import CommandParser


def _command_type(command: Any) -> str | None:
    if isinstance(command, dict):
        return command.get("type")
    return getattr(command, "type", None)


def test_parse_plain_json() -> None:
    parser = CommandParser()

    commands = parser.parse('{"commands":[{"type":"chitchat","text":"你好"}]}')

    assert len(commands) == 1
    assert _command_type(commands[0]) == "chitchat"
    assert commands[0].text == "你好"


def test_parse_json_in_markdown_code_block() -> None:
    parser = CommandParser()
    raw_output = """
```json
{"commands":[{"type":"call_tool","tool_name":"get_logistics_info","arguments":{"order_id":"A123"}}]}
```
"""

    commands = parser.parse(raw_output)

    assert len(commands) == 1
    assert _command_type(commands[0]) == "call_tool"
    assert commands[0].tool_name == "get_logistics_info"
    assert commands[0].arguments == {"order_id": "A123"}


def test_parse_json_with_explanation_text() -> None:
    parser = CommandParser()
    raw_output = """
好的，下面是命令：
{"commands":[{"type":"start_flow","flow_id":"postsale"}]}
请继续处理。
"""

    commands = parser.parse(raw_output)

    assert len(commands) == 1
    assert _command_type(commands[0]) == "start_flow"
    assert commands[0].flow == "postsale"


def test_parse_top_level_list() -> None:
    parser = CommandParser()

    commands = parser.parse('[{"type":"set_slot","name":"order_id","value":"A12345678"}]')

    assert len(commands) == 1
    assert _command_type(commands[0]) == "set_slot"
    assert commands[0].name == "order_id"
    assert commands[0].value == "A12345678"


def test_parse_invalid_json_returns_empty_list() -> None:
    parser = CommandParser()

    commands = parser.parse("这不是合法 JSON: {commands: [}")

    assert commands == []
