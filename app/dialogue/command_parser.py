from __future__ import annotations

import json
import re
from typing import Any

from app.dialogue.commands import (
    CallToolCommand,
    ChitchatCommand,
    Command,
    KnowledgeAnswerCommand,
    SetSlotCommand,
    StartFlowCommand,
)


class CommandParser:
    def parse(self, text: str | None) -> list[Any]:
        if not text:
            return []

        data = self._extract_json_block(text)
        if data is None:
            return []

        if isinstance(data, dict):
            raw_commands = data.get("commands", [])
        elif isinstance(data, list):
            raw_commands = data
        else:
            return []

        if not isinstance(raw_commands, list):
            return []

        commands: list[Any] = []
        for item in raw_commands:
            if not isinstance(item, dict):
                continue
            command = self._parse_command_item(item)
            if command is not None:
                commands.append(command)

        return commands

    def _extract_json_block(self, text: str) -> dict[str, Any] | list[Any] | None:
        text = text.strip()
        candidates = self._json_candidates(text)

        for candidate in candidates:
            data = self._load_json_safely(candidate)
            if data is not None:
                return data

        return None

    def _parse_command_item(self, item: dict[str, Any]) -> Any:
        command_type = item.get("type")

        if command_type == "chitchat":
            return ChitchatCommand(text=str(item.get("text", "")), raw=item)

        if command_type == "knowledge_answer":
            return KnowledgeAnswerCommand(
                query=str(item.get("query", "")),
                top_k=int(item.get("top_k") or 3),
                raw=item,
            )

        if command_type == "call_tool":
            arguments = item.get("arguments")
            return CallToolCommand(
                tool_name=str(item.get("tool_name", "")),
                arguments=dict(arguments) if isinstance(arguments, dict) else {},
                raw=item,
            )

        if command_type == "start_flow":
            flow = item.get("flow_id") or item.get("flow") or ""
            return StartFlowCommand(flow=str(flow), raw=item)

        if command_type == "set_slot":
            return SetSlotCommand(
                name=str(item.get("name", "")),
                value=item.get("value"),
                raw=item,
            )

        # Keep unknown commands as raw dicts so later stages can log/debug them.
        return dict(item)

    def _json_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []

        for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE):
            candidates.append(match.group(1).strip())

        list_start = text.find("[")
        list_end = text.rfind("]")
        if list_start != -1 and list_end != -1 and list_end > list_start:
            candidates.append(text[list_start:list_end + 1])

        object_start = text.find("{")
        object_end = text.rfind("}")
        if object_start != -1 and object_end != -1 and object_end > object_start:
            candidates.append(text[object_start:object_end + 1])

        candidates.append(text)
        return candidates

    def _load_json_safely(self, text: str) -> dict[str, Any] | list[Any] | None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        if isinstance(data, (dict, list)):
            return data
        return None
