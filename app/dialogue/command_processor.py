from __future__ import annotations

from typing import Any

from app.dialogue.commands import Command


class CommandProcessor:
    def process(self, commands: list[Command], tracker: dict[str, Any]) -> None:
        for cmd in commands:
            cmd.run(tracker)