from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BaseCommand:
    raw: dict[str, Any] | None = None

    @property
    def type(self) -> str:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.type}
        if self.raw is not None:
            data["raw"] = dict(self.raw)
        return data


class Command(BaseCommand):
    def run(self, tracker: Any) -> None:
        raise NotImplementedError


@dataclass
class StartFlowCommand(Command):
    flow: str = ""

    @property
    def type(self) -> str:
        return "start_flow"

    def run(self, tracker: Any) -> None:
        tracker["active_flow"] = self.flow
        tracker["flow_step_index"] = 0
        tracker["slot_to_collect"] = None
        tracker.setdefault("slots", {})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["flow"] = self.flow
        return data


@dataclass
class SetSlotCommand(Command):
    name: str = ""
    value: Any = None

    @property
    def type(self) -> str:
        return "set_slot"

    def run(self, tracker: Any) -> None:
        tracker.setdefault("slots", {})
        tracker["slots"][self.name] = self.value

        if tracker.get("slot_to_collect") == self.name:
            tracker["slot_to_collect"] = None

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update({"name": self.name, "value": self.value})
        return data


@dataclass
class ChitchatCommand(BaseCommand):
    text: str = ""

    @property
    def type(self) -> str:
        return "chitchat"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["text"] = self.text
        return data


@dataclass
class KnowledgeAnswerCommand(BaseCommand):
    query: str = ""
    top_k: int = 3

    @property
    def type(self) -> str:
        return "knowledge_answer"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update({"query": self.query, "top_k": int(self.top_k)})
        return data


@dataclass
class CallToolCommand(BaseCommand):
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)

    @property
    def type(self) -> str:
        return "call_tool"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update(
            {
                "tool_name": self.tool_name,
                "arguments": dict(self.arguments),
            }
        )
        return data


def command_to_dict(command: BaseCommand) -> dict[str, Any]:
    return command.to_dict()
