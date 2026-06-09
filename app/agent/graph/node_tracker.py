from __future__ import annotations

from typing import Any

from app.core.tracker import DialogueStateTracker


def _normalize_tracker(tracker: Any, sender_id: str) -> DialogueStateTracker:
    if isinstance(tracker, DialogueStateTracker):
        return tracker
    if isinstance(tracker, dict):
        return DialogueStateTracker.from_dict(tracker)
    return DialogueStateTracker(sender_id=sender_id)


def _clear_started_flow(tracker: Any) -> None:
    if tracker is None:
        return

    active_flow = getattr(tracker, "active_flow", None)
    flow_history = getattr(tracker, "flow_history", None)
    if active_flow and isinstance(flow_history, list):
        flow_history.append(
            {
                "flow_name": active_flow,
                "status": "cancelled",
                "reason": "route_policy_override",
            }
        )

    if hasattr(tracker, "active_flow"):
        tracker.active_flow = None
        tracker.flow_status = "idle"
        tracker.flow_step_index = 0
        tracker.slot_to_collect = None
    elif isinstance(tracker, dict):
        tracker["active_flow"] = None
        tracker["flow_status"] = "idle"
        tracker["flow_step_index"] = 0
        tracker["slot_to_collect"] = None


def _tracker_get_slot(tracker: Any, key: str) -> Any | None:
    if tracker is None:
        return None
    if hasattr(tracker, "get_slot"):
        return tracker.get_slot(key)
    if isinstance(tracker, dict):
        slots = tracker.get("slots")
        if isinstance(slots, dict):
            return slots.get(key)
        return tracker.get(key)
    slots = getattr(tracker, "slots", None)
    if isinstance(slots, dict):
        return slots.get(key)
    return None


def _tracker_set_slot(tracker: Any, key: str, value: Any) -> None:
    if tracker is None:
        return
    if hasattr(tracker, "set_slot"):
        tracker.set_slot(key, value)
        return
    if isinstance(tracker, dict):
        tracker.setdefault("slots", {})[key] = value
        return
    slots = getattr(tracker, "slots", None)
    if isinstance(slots, dict):
        slots[key] = value


def _tracker_clear_slot(tracker: Any, key: str) -> None:
    if tracker is None:
        return
    slots = getattr(tracker, "slots", None)
    if isinstance(slots, dict):
        slots.pop(key, None)
        return
    if isinstance(tracker, dict):
        raw_slots = tracker.get("slots")
        if isinstance(raw_slots, dict):
            raw_slots.pop(key, None)
        tracker.pop(key, None)


def _finish_active_flow(tracker: Any) -> None:
    active_flow = getattr(tracker, "active_flow", None)
    if not active_flow:
        return

    flow_history = getattr(tracker, "flow_history", None)
    if isinstance(flow_history, list):
        flow_history.append(
            {
                "flow_name": active_flow,
                "status": "finished",
            }
        )
    tracker.active_flow = None
    tracker.flow_status = "idle"
    tracker.flow_step_index = 0
    tracker.slot_to_collect = None


def _tracker_tool_snapshot(tracker: Any) -> dict[str, Any]:
    if tracker is None:
        return {}

    if hasattr(tracker, "to_dict"):
        data = tracker.to_dict()
    elif isinstance(tracker, dict):
        data = dict(tracker)
    else:
        data = {
            "sender_id": getattr(tracker, "sender_id", None),
            "slots": getattr(tracker, "slots", None),
            "active_flow": getattr(tracker, "active_flow", None),
            "flow_status": getattr(tracker, "flow_status", None),
            "slot_to_collect": getattr(tracker, "slot_to_collect", None),
        }

    return {
        "sender_id": data.get("sender_id"),
        "slots": dict(data.get("slots") or {}),
        "active_flow": data.get("active_flow"),
        "flow_status": data.get("flow_status"),
        "slot_to_collect": data.get("slot_to_collect"),
        "latest_action_name": data.get("latest_action_name"),
    }
