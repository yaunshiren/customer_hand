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
from app.llm.prompts import PromptBuilder


def _combined_prompt(tracker: Any, user_message: str) -> str:
    system, user = PromptBuilder().build(tracker=tracker, user_message=user_message)
    return f"{system}\n\n{user}"


class FakeLLMCommandGenerator:
    def __init__(self, raw_output: str, success: bool = True) -> None:
        self.raw_output = raw_output
        self.success = success

    def generate(self, prompt: str) -> dict[str, Any]:
        return {
            "success": self.success,
            "raw_output": self.raw_output,
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
            "latency_ms": 1,
            "model": "fake-llm",
            "error": None if self.success else "fake error",
        }


def test_fake_llm_start_flow_and_set_slot_updates_tracker() -> None:
    tracker = DialogueStateTracker("fake_user_postsale")
    prompt = _combined_prompt(tracker, "我要退货")
    fake_llm = FakeLLMCommandGenerator(
        """
        {"commands":[
            {"type":"start_flow","flow_id":"postsale"},
            {"type":"set_slot","name":"order_id","value":"A12345678"}
        ]}
        """
    )

    llm_result = fake_llm.generate(prompt)
    commands = CommandParser().parse(llm_result["raw_output"])
    results = CommandProcessor().process(tracker, commands)

    assert llm_result["success"] is True
    assert len(commands) == 2
    assert len(results) == 2
    assert all(result["success"] for result in results)
    assert tracker.active_flow == "postsale"
    assert tracker.get_slot("order_id") == "A12345678"
    assert any(event.get("command_type") == "start_flow" for event in tracker.events)


def test_fake_llm_call_tool_command_is_recorded_without_network_or_tool_execution() -> None:
    tracker = DialogueStateTracker("fake_user_tool")
    prompt = _combined_prompt(tracker, "帮我查 A123 的物流")
    fake_llm = FakeLLMCommandGenerator(
        """
        好的，命令如下：
        ```json
        {"commands":[{"type":"call_tool","tool_name":"get_logistics_info","arguments":{"order_id":"A123"}}]}
        ```
        """
    )

    llm_result = fake_llm.generate(prompt)
    commands = CommandParser().parse(llm_result["raw_output"])
    results = CommandProcessor().process(tracker, commands)

    assert len(commands) == 1
    assert results[0]["type"] == "call_tool"
    assert results[0]["success"] is True
    assert results[0]["data"]["tool_name"] == "get_logistics_info"
    assert results[0]["data"]["arguments"] == {"order_id": "A123"}
    assert tracker.active_flow is None
    assert any(event.get("command_type") == "call_tool" for event in tracker.events)


def test_fake_llm_failure_returns_no_commands_and_tracker_unchanged() -> None:
    tracker = DialogueStateTracker("fake_user_failure")
    fake_llm = FakeLLMCommandGenerator(raw_output="", success=False)

    llm_result = fake_llm.generate("any prompt")
    commands = CommandParser().parse(llm_result["raw_output"])
    results = CommandProcessor().process(tracker, commands)

    assert llm_result["success"] is False
    assert commands == []
    assert results == []
    assert tracker.active_flow is None
    assert tracker.get_all_slots() == {}
    assert tracker.events == []
