from __future__ import annotations
from turtle import st
from typing import Any

class FlowExecutor:
    def decide_next_action(self, tracker: dict[str, Any], flow_def: dict[str, Any]) -> dict[str, Any]:
        idx = tracker.get("flow_step_index", 0)
        steps = flow_def.get("steps", []) or []

        while True:
            if idx >= len(steps):
                return {
                    "next_action": "action_default_fallback",
                    "slot_to_collect": None,
                    "flow_done": True,
                }

            step = steps[idx]
            step_type = step.get("step_type")

            if step_type == "action":
                next_action = step.get("action")
                tracker["flow_step_index"] = idx + 1
                return {
                    "next_action": next_action,
                    "slot_to_collect": tracker.get("slot_to_collect"),
                    "flow_done": False,
                }
            
            if step_type == "collect":
                slot = step.get("collect")
                slots = tracker.get("slots", {}) or {}
                
                if slot in slots and slots[slot] not in (None, ""):
                    idx = idx + 1
                    tracker["flow_step_index"] = idx
                    continue

                tracker["slot_to_collect"] = slot
                return{
                    "next_action": "action_listen",
                    "slot_to_collect": slot,
                    "flow_done": False,
                }
            
            if step_type == "end":
                tracker["flow_step_index"] = idx + 1
                return{
                    "next_action": "action_listen",
                    "slot_to_collect": None,
                    "flow_done": True,
                }

            idx = idx + 1
            tracker["flow_step_index"] = idx