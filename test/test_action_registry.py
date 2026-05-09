from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.actions.base import Action, ActionResult  # noqa: E402
from app.actions.builtin import register_builtin_actions  # noqa: E402
from app.actions.registry import clear_actions, get_action, register_action  # noqa: E402
from app.core.tracker import DialogueStateTracker  # noqa: E402


@pytest.fixture(autouse=True)
def clean_action_registry():
    clear_actions()
    yield
    clear_actions()


def test_register_action():
    class TestAction(Action):
        name = "test_action_registry"

        def run(self, tracker: Any, **kwargs: Any) -> ActionResult:
            return ActionResult(text="ok")

    register_action(TestAction)

    action = get_action("test_action_registry")
    assert action is not None
    assert action.name == "test_action_registry"
    assert action.run(None).to_dict()["text"] == "ok"


def test_get_unknown_action():
    action = get_action("action_not_exists")

    assert action is None


def test_builtin_action_run():
    register_builtin_actions()
    tracker = DialogueStateTracker("test_user")
    tracker.set_slot("order_id", "A12345678")

    ask_order_action = get_action("action_ask_order_id")
    assert ask_order_action is not None
    ask_result = ask_order_action.run(tracker)
    assert hasattr(ask_result, "to_dict")
    assert ask_result.to_dict()["text"]

    postsale_action = get_action("action_confirm_postsale")
    assert postsale_action is not None
    postsale_result = postsale_action.run(tracker)
    assert hasattr(postsale_result, "to_dict")
    assert "A12345678" in postsale_result.to_dict()["text"]

    logistics_action = get_action("action_show_logistics")
    assert logistics_action is not None
    logistics_result = logistics_action.run(tracker)
    assert hasattr(logistics_result, "to_dict")
    assert "A12345678" in logistics_result.to_dict()["text"]

    fallback_action = get_action("action_default_fallback")
    assert fallback_action is not None
    fallback_result = fallback_action.run(tracker)
    assert hasattr(fallback_result, "to_dict")
    assert fallback_result.to_dict()["text"]
