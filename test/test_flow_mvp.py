from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.actions.builtin import register_builtin_actions  # noqa: E402
from app.actions.registry import clear_actions  # noqa: E402
from app.core.tracker import DialogueStateTracker  # noqa: E402
from app.dialogue.flow_executor import FlowExecutor  # noqa: E402


@pytest.fixture(autouse=True)
def register_actions():
    clear_actions()
    register_builtin_actions()
    yield
    clear_actions()


def test_postsale_two_turns():
    executor = FlowExecutor()
    tracker = DialogueStateTracker("user_postsale")

    action_name = executor.decide_next_action(tracker, "我要退货")
    assert action_name == "action_ask_order_id"

    result = executor._handle_action_step(tracker, action_name)
    assert result.text
    assert "订单号" in result.text

    action_name = executor.decide_next_action(tracker, "A12345678")
    assert action_name == "action_confirm_postsale"
    assert tracker.get_slot("order_id") == "A12345678"

    result = executor._handle_action_step(tracker, action_name)
    assert result.text
    assert "A12345678" in result.text or "售后" in result.text


def test_logistics_two_turns():
    executor = FlowExecutor()
    tracker = DialogueStateTracker("user_logistics")

    action_name = executor.decide_next_action(tracker, "查物流")
    assert action_name == "action_ask_order_id"

    result = executor._handle_action_step(tracker, action_name)
    assert result.text
    assert "订单号" in result.text

    action_name = executor.decide_next_action(tracker, "B98765432")
    assert action_name == "action_show_logistics"
    assert tracker.get_slot("order_id") == "B98765432"

    result = executor._handle_action_step(tracker, action_name)
    assert result.text
    assert "B98765432" in result.text or "物流" in result.text


def test_multi_user_isolated():
    executor = FlowExecutor()
    tracker_a = DialogueStateTracker("user_a")
    tracker_b = DialogueStateTracker("user_b")

    assert executor.decide_next_action(tracker_a, "我要退货") == "action_ask_order_id"
    assert executor.decide_next_action(tracker_a, "A111") == "action_confirm_postsale"

    assert executor.decide_next_action(tracker_b, "查物流") == "action_ask_order_id"
    assert executor.decide_next_action(tracker_b, "B222") == "action_show_logistics"

    assert tracker_a.sender_id != tracker_b.sender_id
    assert tracker_a.get_slot("order_id") == "A111"
    assert tracker_b.get_slot("order_id") == "B222"
    assert tracker_a.active_flow == "postsale"
    assert tracker_b.active_flow == "logistics"


def test_flow_executor_does_not_treat_plain_english_as_order_id():
    executor = FlowExecutor()
    tracker = DialogueStateTracker("user_plain_english")

    tracker.active_flow = "postsale"
    action_name = executor.decide_next_action(tracker, "what products are available")

    assert action_name == "action_default_fallback"
    assert tracker.get_slot("order_id") is None
