from __future__ import annotations
import json
from tracemalloc import start
from typing import Any
from app.dialogue.commands import Command, SetSlotCommand, StartFlowCommand

class CommandParser:
    def parse(self, llm_text: str | None) -> list[Command]:
        if not llm_text:
            return []
        

        # 允许模型前后有多余文本，尽量抽取JSON主体
        payload = self._extract_json_block(llm_text)
        if payload is None:
            return []
        
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []

        commands: list[Command] = []
        for item in data.get("commands", []):
            if not isinstance(item, dict):
                continue

            cmd_type = item.get("type")
            if cmd_type == "start_flow":
                flow = item.get("flow")
                if isinstance(flow, str) and flow:
                    commands.append(StartFlowCommand(flow=flow))
            
            elif cmd_type == "set_slot":
                name = item.get("name")
                if isinstance(name, str) and name and "value" in item:
                    commands.append(SetSlotCommand(name=name, value=item["value"]))
    
        return commands

    

    def _extract_json_block(self, text: str) -> str | None:
        text = text.strip()
        if text.startswith("{") and text.endswith("}"):
            return text
        
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        
        return text[start:end+1]