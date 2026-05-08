from __future__ import annotations

from dataclasses import dataclass
from os import name
from re import T
from typing import Any

class Command:
    def run(self, tracker: dict[str, Any]) ->None:
        raise NotImplementedError

@dataclass
class StartFlowCommand(Command):
    flow: str

    def run(self, tracker: dict[str, Any]) ->None:
        tracker["active_flow"] = self.flow
        tracker["flow_step_index"] = 0
        tracker["slot_to_collect"] = None
        tracker.setdefault("slots", {})
    

@dataclass
class SetSlotCommand(Command):
    name: str
    value: Any

    def run(self, tracker: dict[str, Any]) -> None:
        tracker.setdefault("slots", {})
        tracker["slots"][self.name] = self.value

        # 如果正好在收集这个槽位，收集完成后清空等待状态
        if tracker.get("slot_to_collect") == self.name:
            tracker["slot_to_collect"] = None

