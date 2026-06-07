from __future__ import annotations

import json
from typing import Any

from app.tools.schemas import list_prompt_tool_schemas


class CommandPromptBuilder:
    def build(
        self,
        *,
        tracker: Any,
        user_message: str,
        available_flows: list[dict[str, Any]] | None = None,
        available_tools: list[dict[str, Any]] | None = None,
    ) -> tuple[str, str]:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            tracker=tracker,
            user_message=user_message,
            available_flows=available_flows,
            available_tools=available_tools,
        )
        return system_prompt, user_prompt

    def _build_system_prompt(self) -> str:
        return "\n".join(
            [
                "你是智能客服系统中的命令生成器。",
                "你的任务不是直接自由聊天，而是根据用户输入和会话状态，输出结构化 JSON 命令。",
                "只能输出 JSON，不要输出 Markdown、代码块或自然语言解释。",
                "",
                "输出要求：",
                "- 只能输出 JSON。",
                "- 不要 Markdown。",
                "- 不要代码块。",
                "- 不要自然语言解释。",
                "- commands 必须是 list。",
                "- 每个 command 必须有 type 字段。",
                "",
                "可用命令类型：start_flow / set_slot / chitchat / knowledge_answer / call_tool / ticket",
                "",
                "默认决策规则：",
                "- 用户想退货、退款、售后时，优先输出 start_flow，flow_id 为 postsale。",
                "- 用户想查物流、快递、配送时，优先输出 start_flow，flow_id 为 logistics。",
                "- 如果当前 active_flow 是 postsale 或 logistics，且用户输入像订单号，则输出 set_slot，name 为 order_id。",
                "- 如果用户问退货规则、退款多久到账、售后条件，输出 knowledge_answer。",
                "- 如果用户明确提供订单号并要求查询物流，可以输出 call_tool，tool_name 为 query_logistics。",
                "- 如果用户明确提供订单号并要求查询订单状态，可以输出 call_tool，tool_name 为 query_order。",
                "- 如果用户明确投诉或需要人工跟进，可以输出 call_tool，tool_name 为 create_ticket。",
                "- 如果用户明确提供订单号和发票抬头并要求开票，可以输出 call_tool，tool_name 为 create_invoice。",
                "- 只有在明确需要人工介入时，才输出 ticket；不要因为普通售前、订单、物流、售后问题就直接输出 ticket。",
                "- 触发 ticket 的典型场景：用户明确要求人工、反复表示没解决、知识库低置信度或无法回答、关键信息缺失导致流程卡住。",
                "- ticket 必须包含 text 字段，优先填写用户原话；如果原话过长，可以保留最关键的一句归纳。",
                "- ticket 最好同时包含 reason 字段，说明为什么要转工单，例如 need_human / unresolved / low_confidence / missing_info。",
                "- 如果当前能继续通过 start_flow、set_slot、knowledge_answer 或 call_tool 处理，不要输出 ticket。",
                "- 如果只是“你好”、“谢谢”、“你是谁”，输出 chitchat。",
                "- 不确定时优先输出 knowledge_answer 或 chitchat，不要编造业务结果，也不要过早转 ticket。",
                "- 如果输出 ticket，尽量不要同时输出其他业务命令，避免一边转工单一边继续执行自动流程。",
                "- chitchat 必须包含 text 字段，text 为直接回复用户的自然语言，不能为空。",
                '- 示例：{"commands":[{"type":"ticket","text":"用户想退货但缺少订单号","reason":"missing_info"}]}',
            ]
        )

    def _build_user_prompt(
        self,
        *,
        tracker: Any,
        user_message: str,
        available_flows: list[dict[str, Any]] | None,
        available_tools: list[dict[str, Any]] | None,
    ) -> str:
        state = {
            "sender_id": self._get_sender_id(tracker),
            "slots": self._get_slots(tracker),
            "active_flow": self._get_active_flow(tracker),
            "latest_message": self._get_latest_message(tracker),
            "history": self._get_history(tracker, limit=6),
        }
        flows = available_flows or self._default_flows()
        tools = available_tools or self._default_tools()

        schema = {
            "commands": [
                {"type": "chitchat", "text": "必填，直接回复用户"},
                {"type": "start_flow", "flow_id": "postsale | logistics"},
                {"type": "set_slot", "name": "order_id", "value": "用户提供的值"},
                {"type": "knowledge_answer", "query": "用户问题", "top_k": 3},
                {"type": "call_tool", "tool_name": "工具名", "arguments": {}},
                {"type": "ticket", "text": "用户问题原文", "reason": "low_confidence | need_human | missing_info | unresolved"},
            ]
        }

        return f"""
当前用户输入:
{user_message}

当前会话状态:
```json
{self._to_json(state)}
```

可用 flows:
```json
{self._to_json(flows)}
```

可用 tools:
```json
{self._to_json(tools)}
```

输出 JSON schema:
```json
{self._to_json(schema)}
```

请根据当前用户输入输出 JSON:
""".strip()

    def _get_sender_id(self, tracker: Any) -> str | None:
        if isinstance(tracker, dict):
            return tracker.get("sender_id")
        return getattr(tracker, "sender_id", None)

    def _get_slots(self, tracker: Any) -> dict[str, Any]:
        if hasattr(tracker, "get_all_slots"):
            return tracker.get_all_slots()
        if isinstance(tracker, dict):
            return dict(tracker.get("slots") or {})
        slots = getattr(tracker, "slots", None)
        return dict(slots) if isinstance(slots, dict) else {}

    def _get_active_flow(self, tracker: Any) -> str | None:
        if isinstance(tracker, dict):
            return tracker.get("active_flow")
        return getattr(tracker, "active_flow", None)

    def _get_latest_message(self, tracker: Any) -> str | None:
        if isinstance(tracker, dict):
            return tracker.get("latest_message")
        return getattr(tracker, "latest_message", None)

    def _get_history(self, tracker: Any, limit: int = 6) -> list[dict[str, Any]]:
        if isinstance(tracker, dict):
            events = tracker.get("events") or []
        else:
            events = getattr(tracker, "events", []) or []

        compact_events = []
        for event in events[-limit:]:
            if not isinstance(event, dict):
                continue
            compact_events.append(
                {
                    "event": event.get("event"),
                    "text": event.get("text"),
                    "timestamp": event.get("timestamp"),
                }
            )
        return compact_events

    def _default_flows(self) -> list[dict[str, Any]]:
        return [
            {
                "flow_id": "postsale",
                "description": "售后 / 退货流程",
                "required_slots": ["order_id"],
            },
            {
                "flow_id": "logistics",
                "description": "物流查询流程",
                "required_slots": ["order_id"],
            },
        ]

    def _default_tools(self) -> list[dict[str, Any]]:
        return list_prompt_tool_schemas()

    def _to_json(self, data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2)


PromptBuilder = CommandPromptBuilder
