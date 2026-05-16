from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.agent import Agent  # noqa: E402
from app.core.tracker_store import InMemoryTrackerStore  # noqa: E402
from app.dialogue.command_parser import CommandParser  # noqa: E402
from app.dialogue.command_processor import CommandProcessor  # noqa: E402
from app.dialogue.llm_generator import DEFAULT_CHITCHAT_REPLY  # noqa: E402


class FakeLLMCommandGenerator:
    enabled = True

    def __init__(self, raw_output: str) -> None:
        self.raw_output = raw_output

    def generate(self, tracker: Any, text: str, flow_ids: list[str] | None = None) -> dict[str, Any]:
        llm_result = {
            "success": True,
            "raw_output": self.raw_output,
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
            "latency_ms": 1,
            "model": "fake-llm",
            "error": None,
        }
        raw = self.raw_output.strip()
        if not raw:
            return {"handled": False, "reply_text": None, "results": [], "llm_result": llm_result}
        commands = CommandParser().parse(raw)
        if not commands:
            return {"handled": False, "reply_text": None, "results": [], "llm_result": llm_result}
        results = CommandProcessor().process(tracker, commands)
        reply_text: str | None = None
        for result in results:
            if result.get("type") == "chitchat" and result.get("success") is True:
                t = str(result.get("data", {}).get("text") or "").strip()
                reply_text = t or DEFAULT_CHITCHAT_REPLY
                break
        return {
            "handled": True,
            "reply_text": reply_text,
            "results": results,
            "llm_result": llm_result,
        }


def build_agent_with_fake_llm(raw_output: str) -> tuple[Agent, InMemoryTrackerStore]:
    store = InMemoryTrackerStore()
    agent = Agent(tracker_store=store, flows={})
    agent.llm_generator = FakeLLMCommandGenerator(raw_output)
    return agent, store


def test_llm_chitchat_returns_direct_reply() -> None:
    reply_text = "你好呀～很高兴为您服务！有什么可以帮您的吗？"
    agent, store = build_agent_with_fake_llm(
        f'{{"commands":[{{"type":"chitchat","text":"{reply_text}"}}]}}'
    )

    response = agent.handle_message("你好呀宝宝", "llm_chitchat_user")
    tracker = store.retrieve("llm_chitchat_user")

    assert response[0]["text"] == reply_text
    assert "抱歉，我暂时没有理解你的问题" not in response[0]["text"]
    assert tracker is not None
    assert tracker.get("latest_action_name") == "llm_chitchat"
    assert tracker.latest_bot_message == reply_text


def test_llm_start_flow_postsale_asks_order_id() -> None:
    agent, store = build_agent_with_fake_llm(
        '{"commands":[{"type":"start_flow","flow_id":"postsale"}]}'
    )

    response = agent.handle_message("我买的这件东西不想要了", "llm_postsale_user")
    tracker = store.retrieve("llm_postsale_user")

    assert tracker is not None
    assert tracker.active_flow == "postsale"
    assert "订单号" in response[0]["text"]
    assert tracker.get("latest_action_name") == "action_ask_order_id"
