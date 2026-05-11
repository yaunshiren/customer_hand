from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.actions.base import ActionResult
from app.actions.builtin import register_builtin_actions
from app.actions.registry import get_action
from app.core.tracker_store import InMemoryTrackerStore
from app.dialogue.command_parser import CommandParser
from app.dialogue.command_processor import CommandProcessor
from app.dialogue.flow_executor import FlowExecutor
from app.dialogue.llm_generator import LLMCommandGenerator
from app.dialogue.prompt_builder import PromptBuilder


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Agent:
    def __init__(
        self,
        tracker_store: InMemoryTrackerStore,
        flows: dict[str, Any] | None = None,
    ) -> None:
        register_builtin_actions()
        self.tracker_store = tracker_store
        self.flows = flows or {}
        self.flow_executor = FlowExecutor()

        self.prompt_builder = PromptBuilder()
        self.llm_generator = LLMCommandGenerator()
        self.command_parser = CommandParser()
        self.command_processor = CommandProcessor()

    def handle_message(self, message: str, sender_id: str) -> list[dict[str, Any]]:
        tracker = self.tracker_store.get_or_create(sender_id)
        text = message.strip()
        self._record_user_message(tracker, text)

        llm_result = self._try_llm_commands(tracker, text)
        llm_ok = bool(llm_result.get("handled"))
        llm_reply_text = llm_result.get("reply_text")
        if llm_reply_text:
            return self._final_response(
                tracker=tracker,
                sender_id=sender_id,
                text=llm_reply_text,
                action_name="llm_chitchat",
                metadata={"source": "llm", "command_type": "chitchat"},
            )

        if not llm_ok and self._get_active_flow(tracker) is None:
            self._apply_rule_understanding(tracker, text)

        if self._get_slot_to_collect(tracker) is not None and self._get_active_flow(tracker) is not None:
            self._set_slot(tracker, self._get_slot_to_collect(tracker), text)
            self._set_slot_to_collect(tracker, None)

        next_action = self._decide_next_action(tracker)
        if next_action == "action_ask_order_id":
            self._set_slot_to_collect(tracker, "order_id")

        action = get_action(next_action)
        if action is None:
            next_action = "action_default_fallback"
            action = get_action(next_action)

        result = action.run(tracker) if action else ActionResult(text="系统暂时不可用。")
        for event in result.events:
            tracker["events"].append(event)

        return self._final_response(
            tracker=tracker,
            sender_id=sender_id,
            text=result.text or "",
            action_name=next_action,
            metadata=result.metadata,
        )

    def _try_llm_commands(self, tracker: Any, text: str) -> dict[str, Any]:
        if not self.llm_generator.enabled:
            return {"handled": False, "reply_text": None, "results": []}

        if self._get_active_flow(tracker) is not None:
            return {"handled": False, "reply_text": None, "results": []}

        flow_ids = sorted(self.flows.keys())
        prompt = self.prompt_builder.build(message=text, tracker=tracker, flow_ids=flow_ids)

        try:
            llm_result = self.llm_generator.generate(prompt)
        except Exception as exc:
            tracker["events"].append({
                "event": "llm_error",
                "text": str(exc),
                "timestamp": now_iso(),
            })
            return {"handled": False, "reply_text": None, "results": []}

        if isinstance(llm_result, dict):
            raw = str(llm_result.get("raw_output") or "")
            llm_success = bool(llm_result.get("success"))
            tracker["events"].append({
                "event": "llm_result",
                "text": {
                    "success": llm_success,
                    "usage": llm_result.get("usage"),
                    "latency_ms": llm_result.get("latency_ms"),
                    "model": llm_result.get("model"),
                    "error": llm_result.get("error"),
                },
                "timestamp": now_iso(),
            })
        else:
            raw = str(llm_result or "")
            llm_success = bool(raw)

        tracker["events"].append({
            "event": "llm_raw",
            "text": raw,
            "timestamp": now_iso(),
        })

        if not llm_success or not raw.strip():
            tracker["events"].append({
                "event": "llm_empty",
                "text": "",
                "timestamp": now_iso(),
            })
            return {"handled": False, "reply_text": None, "results": []}

        try:
            commands = self.command_parser.parse(raw)
        except Exception as exc:
            tracker["events"].append({
                "event": "llm_parse_error",
                "text": str(exc),
                "timestamp": now_iso(),
            })
            return {"handled": False, "reply_text": None, "results": []}

        tracker["events"].append({
            "event": "llm_commands",
            "text": str([command.__class__.__name__ for command in commands]),
            "timestamp": now_iso(),
        })

        if not commands:
            tracker["events"].append({
                "event": "llm_parse_failed",
                "text": raw[:200],
                "timestamp": now_iso(),
            })
            return {"handled": False, "reply_text": None, "results": []}

        results = self.command_processor.process(tracker, commands)
        reply_text = None
        for result in results:
            if (
                result.get("type") == "chitchat"
                and result.get("success") is True
                and result.get("data", {}).get("text")
            ):
                reply_text = result["data"]["text"]
                break

        return {"handled": True, "reply_text": reply_text, "results": results}

    def _apply_rule_understanding(self, tracker: Any, text: str) -> None:
        if any(keyword in text for keyword in ("退货", "售后", "退款", "不想要")):
            self._set_active_flow(tracker, "postsale")
        elif any(keyword in text for keyword in ("物流", "快递", "配送")):
            self._set_active_flow(tracker, "logistics")

    def _decide_next_action(self, tracker: Any) -> str:
        active_flow = self._get_active_flow(tracker)
        if not active_flow:
            return "action_default_fallback"

        flow_def = self.flows.get(active_flow)
        if flow_def is None:
            if active_flow == "postsale":
                return "action_confirm_postsale" if self._get_slot(tracker, "order_id") else "action_ask_order_id"
            if active_flow == "logistics":
                return "action_show_logistics" if self._get_slot(tracker, "order_id") else "action_ask_order_id"
            return "action_default_fallback"

        decision = self.flow_executor.decide_next_action(tracker, flow_def)
        next_action = decision.get("next_action") or "action_default_fallback"

        if tracker.get("flow_step_index", 0) >= len(flow_def.get("steps", []) or []):
            self._set_active_flow(tracker, None)
            self._set_slot_to_collect(tracker, None)
            tracker["flow_step_index"] = 0

        return "action_ask_order_id" if next_action == "action_listen" else next_action

    def _record_user_message(self, tracker: Any, text: str) -> None:
        if hasattr(tracker, "update_with_user_message"):
            tracker.update_with_user_message(text)
            return

        tracker["latest_message"] = text
        tracker.setdefault("events", []).append({"event": "user", "text": text, "timestamp": now_iso()})

    def _final_response(
        self,
        *,
        tracker: Any,
        sender_id: str,
        text: str,
        action_name: str,
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        tracker["latest_action_name"] = action_name
        if hasattr(tracker, "add_bot_message"):
            tracker.add_bot_message(text)
        else:
            tracker["latest_bot_message"] = text
            tracker.setdefault("events", []).append({"event": "bot", "text": text, "timestamp": now_iso()})

        self.tracker_store.save(tracker)
        return [{
            "recipient_id": sender_id,
            "text": text,
            "timestamp": now_iso(),
            "metadata": metadata,
        }]

    def _get_active_flow(self, tracker: Any) -> str | None:
        if hasattr(tracker, "active_flow"):
            return tracker.active_flow
        return tracker.get("active_flow")

    def _set_active_flow(self, tracker: Any, flow_name: str | None) -> None:
        if hasattr(tracker, "active_flow"):
            tracker.active_flow = flow_name
        else:
            tracker["active_flow"] = flow_name
        tracker["flow_step_index"] = 0
        tracker["slot_to_collect"] = None
        tracker.setdefault("slots", {})

    def _get_slot_to_collect(self, tracker: Any) -> str | None:
        return tracker.get("slot_to_collect")

    def _set_slot_to_collect(self, tracker: Any, slot_name: str | None) -> None:
        tracker["slot_to_collect"] = slot_name

    def _get_slot(self, tracker: Any, key: str) -> Any:
        if hasattr(tracker, "get_slot"):
            return tracker.get_slot(key)
        return tracker.get("slots", {}).get(key)

    def _set_slot(self, tracker: Any, key: str | None, value: Any) -> None:
        if not key:
            return
        if hasattr(tracker, "set_slot"):
            tracker.set_slot(key, value)
        else:
            tracker.setdefault("slots", {})[key] = value
