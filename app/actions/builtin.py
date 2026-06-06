from __future__ import annotations

from typing import Any

from app.actions.base import Action, ActionResult
from app.actions.registry import register_action


def _get_slot(tracker: Any, key: str, default: Any = None) -> Any:
    if hasattr(tracker, "get_slot"):
        return tracker.get_slot(key, default)

    if isinstance(tracker, dict):
        return tracker.get("slots", {}).get(key, default)

    slots = getattr(tracker, "slots", None)
    if isinstance(slots, dict):
        return slots.get(key, default)

    return default


class ActionAskOrderId(Action):
    name = "action_ask_order_id"

    def run(self, tracker: Any, **kwargs: Any) -> ActionResult:
        return ActionResult(
            text="请提供订单号，我来帮你继续处理。",
            metadata={
                "action": self.name,
                "argument_status": "missing",
                "missing_arguments": ["order_id"],
            },
        )


class ActionConfirmPostsale(Action):
    name = "action_confirm_postsale"

    def run(self, tracker: Any, **kwargs: Any) -> ActionResult:
        order_id = _get_slot(tracker, "order_id")
        if order_id:
            text = f"已收到订单 {order_id} 的售后申请，我们会尽快处理。"
        else:
            text = "还缺少订单号，请先提供订单号。"

        return ActionResult(
            text=text,
            metadata={
                "action": self.name,
                "order_id": order_id,
                "argument_status": "valid" if order_id else "missing",
                "missing_arguments": [] if order_id else ["order_id"],
            },
        )


class ActionShowLogistics(Action):
    name = "action_show_logistics"

    def run(self, tracker: Any, **kwargs: Any) -> ActionResult:
        order_id = _get_slot(tracker, "order_id")
        if order_id:
            text = f"订单 {order_id} 当前物流状态：运输中，预计 1-2 天内送达。"
        else:
            text = "请先提供订单号，我才能帮你查询物流。"

        return ActionResult(
            text=text,
            metadata={
                "action": self.name,
                "order_id": order_id,
                "argument_status": "valid" if order_id else "missing",
                "missing_arguments": [] if order_id else ["order_id"],
            },
        )


class ActionDefaultFallback(Action):
    name = "action_default_fallback"

    def run(self, tracker: Any, **kwargs: Any) -> ActionResult:
        return ActionResult(
            text="抱歉，我暂时没有理解你的问题。你可以尝试说：我要退货、查物流。",
            metadata={"action": self.name},
        )


def register_builtin_actions() -> None:
    register_action(ActionAskOrderId)
    register_action(ActionConfirmPostsale)
    register_action(ActionShowLogistics)
    register_action(ActionDefaultFallback)
