from __future__ import annotations

import logging
from typing import Any

from app.agent.graph.state import AgentState
from app.core.tracker import DialogueStateTracker
from app.dialogue.llm_generator import LLMCommandGenerator
from app.dialogue.command_processor import CommandProcessor
from app.dialogue.command_parser import CommandParser
from app.rag.answerer import KnowledgeAnswerer
from app.actions.registry import get_action
from app.actions.base import ActionResult
from app.tickets import TicketService
from app.actions.builtin import register_builtin_actions

logger = logging.getLogger(__name__)


def _normalize_tracker(tracker: Any, sender_id: str) -> DialogueStateTracker:
    if isinstance(tracker, DialogueStateTracker):
        return tracker
    if isinstance(tracker, dict):
        return DialogueStateTracker.from_dict(tracker)
    return DialogueStateTracker(sender_id=sender_id)


def _has_command_type(results: list[dict[str, Any]], command_type: str) -> bool:
    return any(isinstance(result, dict) and result.get("type") == command_type for result in results)


def _first_command_data(results: list[dict[str, Any]], command_type: str) -> dict[str, Any]:
    for result in results:
        if isinstance(result, dict) and result.get("type") == command_type:
            data = result.get("data")
            if isinstance(data, dict):
                return data
    return {}


def load_context(state: AgentState) -> AgentState:
    sender_id = str(state.get("sender_id") or "default")
    message = str(state.get("message") or "").strip()
    tracker = _normalize_tracker(state.get("tracker"), sender_id)

    tracker.update_with_user_message(message)

    return {
        **state,
        "sender_id": sender_id,
        "message": message,
        "tracker": tracker,
    }


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
    if results and not _has_command_type(results, "start_flow"):
        command_processor.process(tracker, results)

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
        "llm_result": llm_result,
        "llm_results": results,
        "handled": bool(llm_result.get("handled")),
        "reply_text": llm_result.get("reply_text"),
        "command_types": command_types,
    }


def route(state: AgentState) -> AgentState:
    llm_result = state.get("llm_result") or {}
    results = state.get("llm_results") or []
    reply_text = str(state.get("reply_text") or "").strip()
    message = str(state.get("message") or "").strip()
    tracker = state.get("tracker")
    active_flow = getattr(tracker, "active_flow", None) if tracker is not None else None
    llm_generator = state.get("llm_generator")
    llm_enabled = bool(getattr(llm_generator, "enabled", False)) if llm_generator is not None else False

    if _has_command_type(results, "ticket"):
        route_name = "ticket"
    elif _has_command_type(results, "knowledge_answer"):
        route_name = "rag"
    elif _has_command_type(results, "start_flow") or active_flow:
        route_name = "flow"
    elif reply_text:
        route_name = "chitchat"
    elif bool(llm_result.get("handled")):
        route_name = "action"
    elif not llm_enabled and any(keyword in message for keyword in ("退货", "售后", "退款", "不想要", "物流", "快递", "配送")):
        route_name = "flow"
    elif message:
        route_name = "fallback"
    else:
        route_name = "fallback"

    return {
        **state,
        "route": route_name,
    }


def rag(state: AgentState) -> AgentState:
    results = state.get("llm_results") or []
    message = str(state.get("message") or "").strip()
    knowledge_answerer = state.get("knowledge_answerer")

    if not isinstance(knowledge_answerer, KnowledgeAnswerer):
        knowledge_answerer = KnowledgeAnswerer()

    command_data = _first_command_data(results, "knowledge_answer")
    rag_query = str(command_data.get("query") or message)
    top_k = int(command_data.get("top_k") or 3)

    try:
        answer = knowledge_answerer.answer(rag_query, top_k=top_k)
    except Exception as exc:
        logger.exception("rag node failed: %s", exc)
        return {
            **state,
            "error": str(exc),
            "route": "fallback",
            "rag_query": rag_query,
            "rag_matches": [],
            "knowledge_answer": "",
            "used_llm": False,
        }

    return {
        **state,
        "rag_query": rag_query,
        "rag_matches": answer.get("matches", []),
        "knowledge_answer": str(answer.get("answer") or ""),
        "used_llm": bool(answer.get("used_llm")),
    }


def flow(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    message = str(state.get("message") or "").strip()
    flow_result: dict[str, Any] = {}

    if tracker is None:
        return {
            **state,
            "route": "fallback",
            "flow_result": {"next_action": "action_default_fallback", "reason": "missing_tracker"},
            "next_action": "action_default_fallback",
        }

    active_flow = getattr(tracker, "active_flow", None)
    slot_to_collect = getattr(tracker, "slot_to_collect", None)

    if slot_to_collect is not None and active_flow is not None:
        tracker.set_slot(slot_to_collect, message)
        tracker.slot_to_collect = None
        flow_result["collected_slot"] = slot_to_collect

    next_action = "action_default_fallback"
    active_flow = getattr(tracker, "active_flow", None)
    if not active_flow:
        flow_result["reason"] = "no_active_flow"
    elif active_flow in ("postsale", "apply_postsale"):
        next_action = "action_confirm_postsale" if tracker.get_slot("order_id") else "action_ask_order_id"
    elif active_flow in ("logistics", "query_logistics"):
        next_action = "action_show_logistics" if tracker.get_slot("order_id") else "action_ask_order_id"
    else:
        flow_def = (state.get("flows") or {}).get(active_flow) if isinstance(state.get("flows"), dict) else None
        if flow_def is None:
            next_action = "action_default_fallback"
        else:
            flow_result["flow_def"] = flow_def
            next_action = "action_default_fallback"

    if next_action == "action_ask_order_id":
        tracker.slot_to_collect = "order_id"
        tracker.flow_status = "waiting_input"
    elif next_action != "action_default_fallback":
        tracker.flow_status = "running"

    flow_result["next_action"] = next_action
    flow_result["active_flow"] = active_flow
    flow_result["slot_to_collect"] = getattr(tracker, "slot_to_collect", None)

    return {
        **state,
        "flow_result": flow_result,
        "next_action": next_action,
    }


def action(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    next_action = str(state.get("next_action") or "action_default_fallback")
    metadata = dict(state.get("metadata") or {})

    register_builtin_actions()
    action_obj = get_action(next_action)
    if action_obj is None:
        next_action = "action_default_fallback"
        action_obj = get_action(next_action)

    if action_obj is None or tracker is None:
        result = ActionResult(text="系统暂时不可用。", metadata={"action": next_action, "error": "action_not_found"})
        return {
            **state,
            "action_result": result.to_dict(),
            "responses": [{"text": result.text or "", "metadata": result.metadata}],
        }

    try:
        result = action_obj.run(tracker, **metadata)
    except Exception as exc:
        logger.exception("action node failed: %s", exc)
        result = ActionResult(
            text="系统暂时不可用。",
            metadata={"action": next_action, "error": str(exc)},
        )
        return {
            **state,
            "error": str(exc),
            "action_result": result.to_dict(),
            "responses": [{"text": result.text or "", "metadata": result.metadata}],
        }

    return {
        **state,
        "action_result": result.to_dict(),
        "responses": [{"text": result.text or "", "metadata": result.metadata}],
    }


def ticket(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    sender_id = str(state.get("sender_id") or "default")
    message = str(state.get("message") or "").strip()
    llm_results = state.get("llm_results") or []
    ticket_service = state.get("ticket_service")

    if not isinstance(ticket_service, TicketService):
        ticket_service = TicketService()

    ticket_data = _first_command_data(llm_results, "ticket")
    ticket_text = str(ticket_data.get("text") or message)
    ticket = ticket_service.create_ticket(
        sender_id=sender_id,
        text=ticket_text,
        metadata={"source": "ticket"},
        title=ticket_data.get("title"),
        summary=ticket_data.get("summary"),
        category=ticket_data.get("category"),
        priority=ticket_data.get("priority"),
        suggestion=ticket_data.get("suggestion"),
    )

    if tracker is not None:
        tracker.latest_action_name = "ticket_create"

    response_metadata = {
        "source": "ticket",
        "ticket_id": ticket.ticket_id,
        "category": ticket.category,
        "priority": ticket.priority,
    }

    return {
        **state,
        "ticket": {
            "ticket_id": ticket.ticket_id,
            "sender_id": ticket.sender_id,
            "title": ticket.title,
            "summary": ticket.summary,
            "category": ticket.category,
            "priority": ticket.priority,
            "suggestion": ticket.suggestion,
            "status": ticket.status,
            "metadata": ticket.metadata,
        },
        "responses": [
            {
                "recipient_id": sender_id,
                "text": "这个问题需要人工进一步确认，我已经帮你生成工单，客服会根据订单信息继续处理。",
                "metadata": response_metadata,
            }
        ],
        "route": "ticket",
    }


def generate_response(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    sender_id = str(state.get("sender_id") or "default")
    reply_text = str(state.get("reply_text") or "").strip()
    responses = list(state.get("responses") or [])
    action_result = state.get("action_result") or {}
    ticket = state.get("ticket") or {}
    route_name = str(state.get("route") or "fallback")
    rag_matches = state.get("rag_matches") or []
    knowledge_answer = str(state.get("knowledge_answer") or "")
    error = str(state.get("error") or "")

    if reply_text and route_name == "chitchat":
        responses = [
            {
                "recipient_id": sender_id,
                "text": reply_text,
                "metadata": {"source": "llm", "command_type": "chitchat"},
            }
        ]

    if tracker is not None and responses:
        final_text = str(responses[0].get("text") or "")
        tracker.add_bot_message(final_text)
        tracker.latest_action_name = str(action_result.get("metadata", {}).get("action") or tracker.latest_action_name or route_name)

    final_responses = list(responses)
    if not final_responses:
        fallback_text = knowledge_answer or str(action_result.get("text") or "系统暂时不可用。")
        final_responses = [
            {
                "recipient_id": sender_id,
                "text": fallback_text,
                "metadata": {
                    "route": route_name,
                    "rag_match_count": len(rag_matches),
                    "ticket_id": ticket.get("ticket_id"),
                    "error": error or None,
                    **(action_result.get("metadata") or {}),
                },
            }
        ]
        if tracker is not None:
            tracker.add_bot_message(fallback_text)

    return {
        **state,
        "responses": final_responses,
    }


def save_context(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    tracker_store = state.get("tracker_store")

    if tracker_store is not None and tracker is not None:
        tracker_store.save(tracker)

    return {
        **state,
        "saved": True,
    }
