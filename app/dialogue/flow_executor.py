from __future__ import annotations

import re
from typing import Any

from app.actions.base import ActionResult
from app.actions.registry import get_action


class FlowExecutor:
    def decide_next_action(
        self,
        tracker: Any,
        message: str | dict[str, Any],
    ) -> str | dict[str, Any]:
        if isinstance(message, dict):
            return self._decide_from_flow_def(tracker, message)

        return self._decide_from_message(tracker, message)

    def start_flow(self, tracker: Any, flow_name: str) -> None:
        self._set_active_flow(tracker, flow_name)
        self._set_flow_step_index(tracker, 0)
        self._set_slot_to_collect(tracker, None)
        self._set_flow_status(tracker, "running")
        self._append_flow_history(
            tracker,
            {
                "flow_name": flow_name,
                "status": "running",
            },
        )

    def finish_flow(self, tracker: Any, flow_name: str | None = None) -> None:
        current_flow = flow_name or self._get_active_flow(tracker)
        if current_flow is None:
            return
        self._append_flow_history(
            tracker,
            {
                "flow_name": current_flow,
                "status": "finished",
            },
        )
        self._set_active_flow(tracker, None)
        self._set_slot_to_collect(tracker, None)
        self._set_flow_step_index(tracker, 0)
        self._set_flow_status(tracker, "idle")

    def _decide_from_message(self, tracker: Any, message: str) -> str:
        text = message.strip()
        active_flow = self._get_active_flow(tracker)

        if active_flow in ("postsale", "apply_postsale") and self._looks_like_order_id(text):
            self._handle_collect_step(tracker, "order_id", text)
            self._set_flow_status(tracker, "running")
            return "action_confirm_postsale"

        if active_flow in ("logistics", "query_logistics") and self._looks_like_order_id(text):
            self._handle_collect_step(tracker, "order_id", text)
            self._set_flow_status(tracker, "running")
            return "action_show_logistics"

        if "退货" in text or "售后" in text:
            self.start_flow(tracker, "postsale")
            if self._get_slot(tracker, "order_id"):
                return "action_confirm_postsale"
            return "action_ask_order_id"

        if "物流" in text or "快递" in text:
            self.start_flow(tracker, "logistics")
            if self._get_slot(tracker, "order_id"):
                return "action_show_logistics"
            return "action_ask_order_id"

        return "action_default_fallback"

    def _decide_from_flow_def(
        self,
        tracker: Any,
        flow_def: dict[str, Any],
    ) -> dict[str, Any]:
        idx = self._get_flow_step_index(tracker)
        steps = flow_def.get("steps", []) or []

        while True:
            if idx >= len(steps):
                self.finish_flow(tracker, flow_def.get("id") or flow_def.get("name"))
                return {
                    "next_action": "action_default_fallback",
                    "slot_to_collect": None,
                    "flow_done": True,
                }

            step = steps[idx]
            step_type = step.get("step_type")

            if step_type == "action":
                next_action = self._handle_action_step_name(step.get("action"))
                self._set_flow_step_index(tracker, idx + 1)
                self._set_flow_status(tracker, "running")
                return {
                    "next_action": next_action,
                    "slot_to_collect": self._get_slot_to_collect(tracker),
                    "flow_done": False,
                }

            if step_type == "collect":
                slot = step.get("collect")
                if slot and self._get_slot(tracker, slot) not in (None, ""):
                    idx = idx + 1
                    self._set_flow_step_index(tracker, idx)
                    continue

                self._set_slot_to_collect(tracker, slot)
                self._set_flow_status(tracker, "waiting_input")
                return {
                    "next_action": "action_listen",
                    "slot_to_collect": slot,
                    "flow_done": False,
                }

            if step_type == "end":
                self.finish_flow(tracker, flow_def.get("id") or flow_def.get("name"))
                return {
                    "next_action": "action_listen",
                    "slot_to_collect": None,
                    "flow_done": True,
                }

            idx = idx + 1
            self._set_flow_step_index(tracker, idx)

    def _handle_action_step(self, tracker: Any, action_name: str) -> ActionResult:
        action = get_action(action_name)
        if action is None:
            action = get_action("action_default_fallback")

        if action is None:
            return ActionResult(metadata={"action": action_name, "error": "action_not_found"})

        return action.run(tracker)

    def _handle_collect_step(self, tracker: Any, slot_name: str, message: str) -> str | None:
        value = message.strip()
        if not value:
            return None

        self._set_slot(tracker, slot_name, value)
        return value

    def _handle_action_step_name(self, action_name: Any) -> str:
        if isinstance(action_name, str) and action_name:
            return action_name
        return "action_default_fallback"

    def _get_slot(self, tracker: Any, key: str, default: Any = None) -> Any:
        if hasattr(tracker, "get_slot"):
            return tracker.get_slot(key, default)

        if isinstance(tracker, dict):
            return tracker.get("slots", {}).get(key, default)

        slots = getattr(tracker, "slots", None)
        if isinstance(slots, dict):
            return slots.get(key, default)

        return default

    def _set_slot(self, tracker: Any, key: str, value: Any) -> None:
        if hasattr(tracker, "set_slot"):
            tracker.set_slot(key, value)
            return

        if isinstance(tracker, dict):
            tracker.setdefault("slots", {})
            tracker["slots"][key] = value
            return

        slots = getattr(tracker, "slots", None)
        if isinstance(slots, dict):
            slots[key] = value

    def _get_active_flow(self, tracker: Any) -> str | None:
        if isinstance(tracker, dict):
            return tracker.get("active_flow")
        return getattr(tracker, "active_flow", None)

    def _set_active_flow(self, tracker: Any, flow_name: str | None) -> None:
        if isinstance(tracker, dict):
            tracker["active_flow"] = flow_name
            return
        setattr(tracker, "active_flow", flow_name)

    def _get_flow_status(self, tracker: Any) -> str:
        if isinstance(tracker, dict):
            return str(tracker.get("flow_status") or "idle")
        return str(getattr(tracker, "flow_status", "idle"))

    def _set_flow_status(self, tracker: Any, status: str) -> None:
        if isinstance(tracker, dict):
            tracker["flow_status"] = status
            return
        setattr(tracker, "flow_status", status)

    def _get_flow_step_index(self, tracker: Any) -> int:
        if isinstance(tracker, dict):
            return int(tracker.get("flow_step_index", 0) or 0)
        return int(getattr(tracker, "flow_step_index", 0) or 0)

    def _set_flow_step_index(self, tracker: Any, value: int) -> None:
        if isinstance(tracker, dict):
            tracker["flow_step_index"] = int(value)
            return
        setattr(tracker, "flow_step_index", int(value))

    def _get_slot_to_collect(self, tracker: Any) -> str | None:
        if isinstance(tracker, dict):
            return tracker.get("slot_to_collect")
        return getattr(tracker, "slot_to_collect", None)

    def _set_slot_to_collect(self, tracker: Any, slot_name: str | None) -> None:
        if isinstance(tracker, dict):
            tracker["slot_to_collect"] = slot_name
            return
        setattr(tracker, "slot_to_collect", slot_name)

    def _append_flow_history(self, tracker: Any, item: dict[str, Any]) -> None:
        if isinstance(tracker, dict):
            tracker.setdefault("flow_history", []).append(item)
            return
        history = getattr(tracker, "flow_history", None)
        if history is None:
            history = []
            setattr(tracker, "flow_history", history)
        history.append(item)

    def _looks_like_order_id(self, message: str) -> bool:
        text = message.strip()
        if len(text) < 4 or len(text) > 64:
            return False

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", text):
            return False

        return any(ch.isdigit() for ch in text)
