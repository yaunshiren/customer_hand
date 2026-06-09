from __future__ import annotations

import logging
from typing import Any

from app.agent.graph.state import AgentState
from app.agent.graph.node_services import (
    _build_business_question_classifier,
    _build_intent_classifier,
    _build_tool_safety_policy,
)
from app.agent.graph.node_shared import _has_command_type, _model_dump
from app.agent.graph.node_tooling import _pending_tool_confirmation
from app.agent.tool_safety import is_cancellation_message, is_confirmation_message
from app.dialogue.command_parser import CommandParser
from app.dialogue.command_processor import CommandProcessor
from app.dialogue.llm_generator import LLMCommandGenerator

logger = logging.getLogger(__name__)


def _can_skip_llm_understanding(classification: Any) -> bool:
    data = _model_dump(classification)
    if not data:
        return False
    route_name = str(data.get("route") or "").strip()
    question_type = str(data.get("question_type") or "").strip()
    confidence = float(data.get("confidence") or 0.0)
    return route_name in {"tool", "clarify"} and question_type != "unknown" and confidence >= 0.7


def _can_skip_llm_for_pending_confirmation(state: AgentState, message: str, tracker: Any) -> bool:
    pending = _pending_tool_confirmation(tracker)
    if not pending:
        return False
    policy = _build_tool_safety_policy(state)
    return is_confirmation_message(message, policy) or is_cancellation_message(message, policy)


def _classify_intent(state: AgentState, message: str) -> Any | None:
    if not message:
        return None
    try:
        return _build_intent_classifier(state).classify(message)
    except Exception as exc:
        logger.exception("intent classify failed: %s", exc)
        return None


def _classify_business_question(state: AgentState, message: str, tracker: Any, intent_result: Any | None) -> Any | None:
    if not message:
        return None
    try:
        return _build_business_question_classifier(state).classify(
            message,
            intent_result=intent_result,
            tracker=tracker,
            user_id=str(state.get("sender_id") or "") or None,
        )
    except Exception as exc:
        logger.exception("business classify failed: %s", exc)
        return None


def understand(state: AgentState) -> AgentState:
    sender_id = str(state.get("sender_id") or "default")
    message = str(state.get("message") or "").strip()
    tracker = state.get("tracker")
    llm_generator = state.get("llm_generator")

    if llm_generator is None or not hasattr(llm_generator, "generate"):
        llm_generator = LLMCommandGenerator()

    state = {
        **state,
        "llm_generator": llm_generator,
    }
    intent_result: Any | None = None
    business_classification = _classify_business_question(state, message, tracker, None)

    if _can_skip_llm_for_pending_confirmation(state, message, tracker) or _can_skip_llm_understanding(business_classification):
        return {
            **state,
            "sender_id": sender_id,
            "message": message,
            "intent_result": intent_result,
            "business_classification": business_classification,
            "llm_result": {
                "handled": False,
                "reply_text": None,
                "results": [],
                "skipped": True,
                "reason": "deterministic_business_route",
            },
            "llm_results": [],
            "handled": False,
            "reply_text": None,
            "command_types": [],
        }

    intent_result = _classify_intent(state, message)
    business_classification = _classify_business_question(state, message, tracker, intent_result)

    if _can_skip_llm_understanding(business_classification):
        return {
            **state,
            "sender_id": sender_id,
            "message": message,
            "intent_result": intent_result,
            "business_classification": business_classification,
            "llm_result": {
                "handled": False,
                "reply_text": None,
                "results": [],
                "skipped": True,
                "reason": "deterministic_business_route_after_intent",
            },
            "llm_results": [],
            "handled": False,
            "reply_text": None,
            "command_types": [],
        }

    flow_ids = sorted((state.get("flows") or {}).keys()) if isinstance(state.get("flows"), dict) else []

    command_processor = state.get("command_processor")
    if command_processor is None or not hasattr(command_processor, "process"):
        command_processor = CommandProcessor()
    command_parser = state.get("command_parser")
    if command_parser is None or not hasattr(command_parser, "parse"):
        command_parser = CommandParser()

    try:
        llm_result = llm_generator.generate(tracker, message, flow_ids=flow_ids)
    except Exception as exc:
        logger.exception("understand node failed: %s", exc)
        return {
            **state,
            "sender_id": sender_id,
            "message": message,
            "error": str(exc),
            "intent_result": intent_result,
            "business_classification": business_classification,
            "llm_result": {"handled": False, "reply_text": None, "results": []},
            "llm_results": [],
        }

    results = llm_result.get("results") or []
    if not results:
        raw = str(llm_result.get("raw_output") or "").strip()
        parsed_commands = command_parser.parse(raw)
        if parsed_commands:
            results = command_processor.process(tracker, parsed_commands)
        else:
            reply_text = llm_result.get("reply_text")
            if reply_text:
                results = [{"type": "chitchat", "success": True, "data": {"text": reply_text}}]

    command_types = [result.get("type") for result in results if isinstance(result, dict)]
    if _has_command_type(results, "start_flow") and tracker is not None:
        for result in results:
            if isinstance(result, dict) and result.get("type") == "start_flow":
                data = result.get("data") or {}
                flow_id = str(data.get("flow_id") or data.get("flow") or "").strip()
                if flow_id:
                    tracker.active_flow = flow_id
                    tracker.flow_status = "running"
                    tracker.flow_step_index = 0
                    tracker.slot_to_collect = None
                break

    return {
        **state,
        "sender_id": sender_id,
        "message": message,
        "intent_result": intent_result,
        "business_classification": business_classification,
        "llm_result": llm_result,
        "llm_results": results,
        "handled": bool(llm_result.get("handled")),
        "reply_text": llm_result.get("reply_text"),
        "command_types": command_types,
    }
