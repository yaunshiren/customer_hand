from __future__ import annotations

from datetime import datetime
from typing import Any


class CommandProcessor:
    def process(self, tracker: Any, commands: list[Any] | None = None) -> list[dict[str, Any]]:
        """Apply parsed LLM commands to tracker and return execution results.

        The preferred call style is process(tracker, commands). A small
        compatibility branch keeps the old process(commands, tracker) order
        working until the Agent is updated in a later task.
        """
        if isinstance(tracker, list) and commands is not None:
            tracker, commands = commands, tracker

        results: list[dict[str, Any]] = []
        for command in commands or []:
            command_type = self._get_command_type(command)

            if command_type == "start_flow":
                results.append(self._handle_start_flow(tracker, command))
            elif command_type == "set_slot":
                results.append(self._handle_set_slot(tracker, command))
            elif command_type in {"chitchat", "knowledge_answer", "call_tool"}:
                results.append(self._handle_special_command(tracker, command))
            else:
                result = {
                    "type": command_type or "unknown",
                    "success": False,
                    "message": f"Unknown command type: {command_type}",
                    "data": self._command_to_dict(command),
                }
                self._append_event(
                    tracker,
                    {
                        "event": "command",
                        "command_type": command_type or "unknown",
                        "success": False,
                        "timestamp": self._now(),
                    },
                )
                results.append(result)

        return results

    def _handle_start_flow(self, tracker: Any, command: Any) -> dict[str, Any]:
        flow_id = self._get_command_value(command, "flow_id")
        if flow_id is None:
            flow_id = self._get_command_value(command, "flow")

        if not flow_id:
            return {
                "type": "start_flow",
                "success": False,
                "message": "Missing flow_id",
                "data": {"flow_id": flow_id},
            }

        flow_id = str(flow_id)
        self._set_active_flow(tracker, flow_id)
        self._set_flow_status(tracker, "running")
        self._set_flow_step_index(tracker, 0)
        self._set_slot_to_collect(tracker, None)
        self._append_flow_history(
            tracker,
            {
                "flow_name": flow_id,
                "status": "running",
                "started_at": self._now(),
            },
        )
        self._append_event(
            tracker,
            {
                "event": "command",
                "command_type": "start_flow",
                "flow_id": flow_id,
                "timestamp": self._now(),
            },
        )
        self._touch_tracker(tracker)

        return {
            "type": "start_flow",
            "success": True,
            "message": f"Flow started: {flow_id}",
            "data": {"flow_id": flow_id},
        }

    def _handle_set_slot(self, tracker: Any, command: Any) -> dict[str, Any]:
        name = self._get_command_value(command, "name")
        value = self._get_command_value(command, "value")

        if not name:
            return {
                "type": "set_slot",
                "success": False,
                "message": "Missing slot name",
                "data": {"name": name, "value": value},
            }

        slot_name = str(name)
        self._set_slot(tracker, slot_name, value)
        if slot_name == self._get_slot_to_collect(tracker):
            self._set_slot_to_collect(tracker, None)
        self._append_event(
            tracker,
            {
                "event": "command",
                "command_type": "set_slot",
                "name": slot_name,
                "value": value,
                "timestamp": self._now(),
            },
        )
        self._touch_tracker(tracker)

        return {
            "type": "set_slot",
            "success": True,
            "message": f"Slot set: {slot_name}",
            "data": {"name": slot_name, "value": value},
        }

    def _handle_special_command(self, tracker: Any, command: Any) -> dict[str, Any]:
        command_type = self._get_command_type(command)
        data: dict[str, Any]
        message: str

        if command_type == "chitchat":
            data = {"text": self._get_command_value(command, "text", "")}
            message = "Chitchat command recorded"
        elif command_type == "knowledge_answer":
            data = {
                "query": self._get_command_value(command, "query", ""),
                "top_k": self._get_command_value(command, "top_k", 3),
            }
            message = "Knowledge answer command recorded"
        elif command_type == "call_tool":
            arguments = self._get_command_value(command, "arguments", {})
            data = {
                "tool_name": self._get_command_value(command, "tool_name", ""),
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
            message = "Tool call command recorded"
        else:
            data = self._command_to_dict(command)
            message = f"Unknown special command: {command_type}"

        self._append_event(
            tracker,
            {
                "event": "command",
                "command_type": command_type,
                "data": data,
                "timestamp": self._now(),
            },
        )
        self._touch_tracker(tracker)

        return {
            "type": command_type or "unknown",
            "success": True,
            "message": message,
            "data": data,
        }

    def _get_command_type(self, command: Any) -> str | None:
        if isinstance(command, dict):
            value = command.get("type")
        else:
            value = getattr(command, "type", None)
        return str(value) if value is not None else None

    def _get_command_value(self, command: Any, key: str, default: Any = None) -> Any:
        if isinstance(command, dict):
            return command.get(key, default)

        if hasattr(command, key):
            return getattr(command, key)

        if hasattr(command, "to_dict"):
            data = command.to_dict()
            return data.get(key, default)

        return default

    def _append_event(self, tracker: Any, event: dict[str, Any]) -> None:
        if hasattr(tracker, "events"):
            tracker.events.append(event)
            return

        if isinstance(tracker, dict):
            tracker.setdefault("events", []).append(event)

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _set_active_flow(self, tracker: Any, flow_id: str) -> None:
        if hasattr(tracker, "active_flow"):
            tracker.active_flow = flow_id
            return

        if isinstance(tracker, dict):
            tracker["active_flow"] = flow_id

    def _set_slot(self, tracker: Any, name: str, value: Any) -> None:
        if hasattr(tracker, "set_slot"):
            tracker.set_slot(name, value)
            return

        if isinstance(tracker, dict):
            tracker.setdefault("slots", {})[name] = value
            if tracker.get("slot_to_collect") == name:
                tracker["slot_to_collect"] = None

    def _touch_tracker(self, tracker: Any) -> None:
        if hasattr(tracker, "updated_at"):
            tracker.updated_at = self._now()
        elif isinstance(tracker, dict):
            tracker["updated_at"] = self._now()

    def _set_flow_status(self, tracker: Any, status: str) -> None:
        if hasattr(tracker, "flow_status"):
            tracker.flow_status = status
            return
        if isinstance(tracker, dict):
            tracker["flow_status"] = status

    def _get_slot_to_collect(self, tracker: Any) -> str | None:
        if hasattr(tracker, "slot_to_collect"):
            return tracker.slot_to_collect
        if isinstance(tracker, dict):
            return tracker.get("slot_to_collect")
        return None

    def _set_slot_to_collect(self, tracker: Any, slot_name: str | None) -> None:
        if hasattr(tracker, "slot_to_collect"):
            tracker.slot_to_collect = slot_name
            return
        if isinstance(tracker, dict):
            tracker["slot_to_collect"] = slot_name

    def _set_flow_step_index(self, tracker: Any, value: int) -> None:
        if hasattr(tracker, "flow_step_index"):
            tracker.flow_step_index = int(value)
            return
        if isinstance(tracker, dict):
            tracker["flow_step_index"] = int(value)

    def _append_flow_history(self, tracker: Any, item: dict[str, Any]) -> None:
        if hasattr(tracker, "flow_history"):
            tracker.flow_history.append(item)
            return
        if isinstance(tracker, dict):
            tracker.setdefault("flow_history", []).append(item)

    def _command_to_dict(self, command: Any) -> dict[str, Any]:
        if isinstance(command, dict):
            return dict(command)
        if hasattr(command, "to_dict"):
            return command.to_dict()
        return {"repr": repr(command)}
