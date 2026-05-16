from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.actions.base import ActionResult
from app.actions.builtin import register_builtin_actions
from app.actions.registry import get_action
from app.core.tracker_store import InMemoryTrackerStore
from app.dialogue.flow_executor import FlowExecutor
from app.dialogue.llm_generator import LLMCommandGenerator
from app.llm.prompts import PromptBuilder
from app.rag.answerer import KnowledgeAnswerer
from app.utils.telemetry import emit_llm_event

logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Agent:
    def __init__(
        self,
        tracker_store: InMemoryTrackerStore,
        flows: dict[str, Any] | None = None,
        knowledge_dir: Path | None = None,
    ) -> None:
        register_builtin_actions()
        self.tracker_store = tracker_store
        self.flows = flows or {}
        self.flow_executor = FlowExecutor()

        self.prompt_builder = PromptBuilder()
        self.llm_generator = LLMCommandGenerator()
        self.knowledge_answerer = KnowledgeAnswerer(docs_dir=knowledge_dir)

    def handle_message(self, message: str, sender_id: str) -> list[dict[str, Any]]:
        text = message.strip()
        logger.info("agent.start sender_id=%s message_len=%d", sender_id, len(text))
        try:
            tracker = self.tracker_store.get_or_create(sender_id)
            self._record_user_message(tracker, text)

            llm_result = self._try_llm_commands(tracker, text)
            if llm_result.get("reply_text"):
                return self._final_response(
                    tracker=tracker,
                    sender_id=sender_id,
                    text=str(llm_result["reply_text"]),
                    action_name="llm_chitchat",
                    metadata={"source": "llm", "command_type": "chitchat"},
                )

            if self._has_command_type(tracker, "knowledge_answer"):
                rag_query = self._rag_query_for_knowledge_answer(tracker, text)
                answer = self.knowledge_answerer.answer(rag_query, top_k=3)
                return self._final_response(
                    tracker=tracker,
                    sender_id=sender_id,
                    text=str(answer.get("answer") or ""),
                    action_name="knowledge_answer",
                    metadata={
                        "source": "rag",
                        "matches": answer.get("matches", []),
                        "used_llm": answer.get("used_llm", False),
                    },
                )

            if not llm_result.get("handled") and self._get_active_flow(tracker) is None:
                self._apply_rule_understanding(tracker, text)

            slot_to_collect = self._get_slot_to_collect(tracker)
            if slot_to_collect is not None and self._get_active_flow(tracker) is not None:
                self._set_slot(tracker, slot_to_collect, text)
                self._set_slot_to_collect(tracker, None)

            next_action = self._decide_next_action(tracker)
            if next_action == "action_ask_order_id":
                self._set_slot_to_collect(tracker, "order_id")
                self._set_flow_status(tracker, "waiting_input")

            action = get_action(next_action)
            if action is None:
                next_action = "action_default_fallback"
                action = get_action(next_action)

            result = action.run(tracker) if action else ActionResult(text="系统暂时不可用。")
            for event in result.events:
                tracker.events.append(event)

            return self._final_response(
                tracker=tracker,
                sender_id=sender_id,
                text=result.text or "",
                action_name=next_action,
                metadata=result.metadata,
            )
        finally:
            logger.info("agent.done sender_id=%s", sender_id)

    def _try_llm_commands(self, tracker: Any, text: str) -> dict[str, Any]:
        if not self.llm_generator.enabled:
            return {"handled": False, "reply_text": None, "results": []}

        flow_ids = sorted(self.flows.keys())
        try:
            llm_result = self.llm_generator.generate(tracker, text, flow_ids=flow_ids)
        except Exception as exc:
            emit_llm_event("command_pipeline.exception", error=str(exc))
            self._add_event(tracker, "llm_error", text=str(exc))
            return {"handled": False, "reply_text": None, "results": []}

        self._add_event(
            tracker,
            "llm_result",
            text={
                "success": bool(llm_result.get("llm_result", {}).get("success")),
                "usage": llm_result.get("llm_result", {}).get("usage"),
                "latency_ms": llm_result.get("llm_result", {}).get("latency_ms"),
                "model": llm_result.get("llm_result", {}).get("model"),
                "error": llm_result.get("llm_result", {}).get("error"),
            },
        )

        raw = str(llm_result.get("llm_result", {}).get("raw_output") or "")
        self._add_event(tracker, "llm_raw", text=raw)

        if not llm_result.get("handled"):
            if not raw.strip():
                self._add_event(tracker, "llm_empty", text="")
            else:
                self._add_event(tracker, "llm_parse_failed", text=raw[:200])
            return {"handled": False, "reply_text": None, "results": []}

        results = llm_result.get("results") or []
        command_types = [result.get("type") for result in results if isinstance(result, dict)]
        self._add_event(tracker, "llm_commands", text=str(command_types))

        return {"handled": True, "reply_text": llm_result.get("reply_text"), "results": results}

    def _apply_rule_understanding(self, tracker: Any, text: str) -> None:
        if any(keyword in text for keyword in ("退货", "售后", "退款", "不想要")):
            self._set_flow(tracker, "postsale")
        elif any(keyword in text for keyword in ("物流", "快递", "配送")):
            self._set_flow(tracker, "logistics")

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

        if bool(decision.get("flow_done")):
            self.flow_executor.finish_flow(tracker, active_flow)

        return "action_ask_order_id" if next_action == "action_listen" else next_action

    def _record_user_message(self, tracker: Any, text: str) -> None:
        if hasattr(tracker, "update_with_user_message"):
            tracker.update_with_user_message(text)
            return

        tracker["latest_message"] = text
        self._add_event(tracker, "user", text=text)

    def _final_response(
        self,
        *,
        tracker: Any,
        sender_id: str,
        text: str,
        action_name: str,
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        self._set_latest_action_name(tracker, action_name)
        if hasattr(tracker, "add_bot_message"):
            tracker.add_bot_message(text)
        else:
            tracker["latest_bot_message"] = text
            self._add_event(tracker, "bot", text=text)

        self.tracker_store.save(tracker)
        return [
            {
                "recipient_id": sender_id,
                "text": text,
                "timestamp": now_iso(),
                "metadata": metadata,
            }
        ]

    def _get_active_flow(self, tracker: Any) -> str | None:
        if hasattr(tracker, "active_flow"):
            return tracker.active_flow
        return tracker.get("active_flow")

    def _set_flow(self, tracker: Any, flow_name: str | None) -> None:
        self._set_active_flow(tracker, flow_name)
        self._set_flow_status(tracker, "running" if flow_name else "idle")
        if flow_name:
            self.flow_executor.start_flow(tracker, flow_name)

    def _set_active_flow(self, tracker: Any, flow_name: str | None) -> None:
        if hasattr(tracker, "active_flow"):
            tracker.active_flow = flow_name
        else:
            tracker["active_flow"] = flow_name

    def _get_flow_status(self, tracker: Any) -> str:
        if hasattr(tracker, "flow_status"):
            return str(tracker.flow_status)
        return str(tracker.get("flow_status", "idle"))

    def _set_flow_status(self, tracker: Any, status: str) -> None:
        if hasattr(tracker, "flow_status"):
            tracker.flow_status = status
        else:
            tracker["flow_status"] = status

    def _get_flow_step_index(self, tracker: Any) -> int:
        if hasattr(tracker, "flow_step_index"):
            return int(tracker.flow_step_index)
        return int(tracker.get("flow_step_index", 0) or 0)

    def _set_flow_step_index(self, tracker: Any, value: int) -> None:
        if hasattr(tracker, "flow_step_index"):
            tracker.flow_step_index = int(value)
        else:
            tracker["flow_step_index"] = int(value)

    def _get_slot_to_collect(self, tracker: Any) -> str | None:
        if hasattr(tracker, "slot_to_collect"):
            return tracker.slot_to_collect
        return tracker.get("slot_to_collect")

    def _set_slot_to_collect(self, tracker: Any, slot_name: str | None) -> None:
        if hasattr(tracker, "slot_to_collect"):
            tracker.slot_to_collect = slot_name
        else:
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

    def _set_latest_action_name(self, tracker: Any, action_name: str) -> None:
        if hasattr(tracker, "latest_action_name"):
            tracker.latest_action_name = action_name
        else:
            tracker["latest_action_name"] = action_name

    def _has_command_type(self, tracker: Any, command_type: str) -> bool:
        for event in reversed(getattr(tracker, "events", []) or tracker.get("events", [])):
            if isinstance(event, dict) and event.get("event") == "command" and event.get("command_type") == command_type:
                return True
        return False

    def _rag_query_for_knowledge_answer(self, tracker: Any, fallback: str) -> str:
        """优先用 LLM 命令里的 query 检索；与整句用户输入相比更贴近检索意图。"""
        for event in reversed(getattr(tracker, "events", []) or tracker.get("events", [])):
            if not isinstance(event, dict):
                continue
            if event.get("event") != "command" or event.get("command_type") != "knowledge_answer":
                continue
            data = event.get("data") or {}
            q = str(data.get("query") or "").strip()
            return q or fallback
        return fallback

    def _add_event(self, tracker: Any, event_type: str, **data: Any) -> None:
        if hasattr(tracker, "events"):
            tracker.events.append(
                {
                    "event": event_type,
                    "timestamp": now_iso(),
                    **data,
                }
            )
            return
        tracker.setdefault("events", []).append(
            {
                "event": event_type,
                "timestamp": now_iso(),
                **data,
            }
        )
