from __future__ import annotations
from typing import Any

class PromptBuilder:
    def build(
        self,
        message: str,
        tracker: dict[str, Any],
        flow_ids: list[str],
    ) -> str:

        active_flow = tracker.get("active_flow")
        slot_to_collect = tracker.get("slot_to_collect")
        slots = tracker.get("slots", {})

        return f"""
你是客服系统的命令生成器。你只能输出JSON,不要输出任何解释。

可用命令：
1) start_flow
格式：{{"type": "start_flow", "flow": "<flow_id>"}}

2) set_slot
格式：{{"type": "set_slot", "name": "<slot_name>", "value": "<slot_value>"}}

可用flow_id: {flow_ids}
当前 active_flow: {active_flow}
当前 slot_to_collect: {slot_to_collect}
当前 slots: {slots}
用户输入：{message}

请严格按照以下格式输出（仅 JSON):
{{
    "commands":[
    ...

    ]
}}
""".strip()