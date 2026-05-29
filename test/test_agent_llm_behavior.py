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

    assert len(response) == 1
    assert response[0]["text"]
    assert tracker is not None
    assert tracker.latest_bot_message is not None
    command_events = [event for event in tracker.events if event.get("event") == "command"]
    assert len(command_events) == 1
    assert command_events[0].get("data", {}).get("text") == reply_text


def test_llm_start_flow_postsale_asks_order_id() -> None:
    agent, store = build_agent_with_fake_llm(
        '{"commands":[{"type":"start_flow","flow_id":"postsale"}]}'
    )

    response = agent.handle_message("我买的这件东西不想要了", "llm_postsale_user")
    tracker = store.retrieve("llm_postsale_user")

    assert tracker is not None
    assert len(response) == 1
    assert response[0]["text"]
    assert tracker.latest_action_name is not None


class FakeLLMCommandGeneratorByMessage:
    enabled = True

    def __init__(self, outputs_by_message: dict[str, str]) -> None:
        self.outputs_by_message = outputs_by_message

    def generate(self, tracker: Any, text: str, flow_ids: list[str] | None = None) -> dict[str, Any]:
        raw_output = self.outputs_by_message.get(text.strip(), "")
        return FakeLLMCommandGenerator(raw_output).generate(tracker, text, flow_ids=flow_ids)


def test_start_flow_after_knowledge_answer_does_not_repeat_rag() -> None:
    """回归：上一轮 knowledge_answer 不应污染本轮 start_flow。"""
    store = InMemoryTrackerStore()
    agent = Agent(tracker_store=store, flows={})
    agent.llm_generator = FakeLLMCommandGeneratorByMessage(
        {
            "退货规则是什么": '{"commands":[{"type":"knowledge_answer","query":"退货规则是什么","top_k":3}]}',
            "我要退货": '{"commands":[{"type":"start_flow","flow_id":"postsale"}]}',
        }
    )

    agent.handle_message("退货规则是什么", "regression_user")
    response = agent.handle_message("我要退货", "regression_user")
    tracker = store.retrieve("regression_user")

    assert tracker is not None
    assert len(response) == 1
    assert response[0]["text"]
    assert tracker.latest_action_name is not None


def test_chitchat_during_active_flow_does_not_fill_order_id() -> None:
    store = InMemoryTrackerStore()
    agent = Agent(tracker_store=store, flows={})
    agent.llm_generator = FakeLLMCommandGeneratorByMessage(
        {
            "return item": '{"commands":[{"type":"start_flow","flow_id":"postsale"}]}',
            "what products are available": (
                '{"commands":[{"type":"chitchat","text":"We sell home goods."}]}'
            ),
        }
    )

    agent.handle_message("return item", "side_question_user")
    response = agent.handle_message("what products are available", "side_question_user")
    tracker = store.retrieve("side_question_user")

    assert tracker is not None
    assert response[0]["text"] == "We sell home goods."
    assert tracker.get_slot("order_id") is None
    assert tracker.active_flow == "postsale"
    assert tracker.slot_to_collect == "order_id"


def test_active_flow_rejects_invalid_order_id_text_when_llm_unhandled() -> None:
    store = InMemoryTrackerStore()
    agent = Agent(tracker_store=store, flows={})
    agent.llm_generator = FakeLLMCommandGeneratorByMessage(
        {
            "return item": '{"commands":[{"type":"start_flow","flow_id":"postsale"}]}',
            "what products are available": "",
        }
    )

    agent.handle_message("return item", "invalid_slot_user")
    response = agent.handle_message("what products are available", "invalid_slot_user")
    tracker = store.retrieve("invalid_slot_user")

    assert tracker is not None
    assert response[0]["text"]
    assert tracker.get_slot("order_id") is None
    assert tracker.active_flow == "postsale"
    assert tracker.slot_to_collect == "order_id"


def test_postsale_flow_finishes_after_confirming_order_id() -> None:
    store = InMemoryTrackerStore()
    agent = Agent(tracker_store=store, flows={})
    agent.llm_generator = FakeLLMCommandGeneratorByMessage(
        {
            "return item": '{"commands":[{"type":"start_flow","flow_id":"postsale"}]}',
            "A1234": '{"commands":[{"type":"set_slot","name":"order_id","value":"A1234"}]}',
        }
    )

    agent.handle_message("return item", "finish_flow_user")
    response = agent.handle_message("A1234", "finish_flow_user")
    tracker = store.retrieve("finish_flow_user")

    assert tracker is not None
    assert response[0]["text"]
    assert tracker.get_slot("order_id") == "A1234"
    assert tracker.active_flow is None
    assert tracker.flow_status == "idle"
    assert tracker.slot_to_collect is None
