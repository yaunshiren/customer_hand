from __future__ import annotations

import logging
import time
from typing import Any

from app.actions.base import ActionResult
from app.actions.builtin import register_builtin_actions
from app.actions.registry import get_action
from app.agent.graph.state import AgentState
from app.agent.graph.node_shared import _elapsed_ms, _first_command_data, _is_likely_order_id, _model_dump
from app.agent.graph.node_tracker import _finish_active_flow, _tracker_tool_snapshot
from app.agent.graph.node_tooling import _invoke_business_tool, _tool_failure_text, _tool_success_text
from app.persistence.tool_recorder import record_tool_trace
from app.tickets import TicketService

logger = logging.getLogger(__name__)


def _action_arguments(next_action: str, tracker: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": next_action,
        "tracker": _tracker_tool_snapshot(tracker),
        "metadata": metadata,
    }


def _ticket_arguments(
    *,
    sender_id: str,
    ticket_text: str,
    ticket_data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "sender_id": sender_id,
        "text": ticket_text,
        "title": ticket_data.get("title"),
        "summary": ticket_data.get("summary"),
        "category": ticket_data.get("category"),
        "priority": ticket_data.get("priority"),
        "suggestion": ticket_data.get("suggestion"),
        "reason": ticket_data.get("reason"),
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
        if slot_to_collect == "order_id" and not _is_likely_order_id(message):
            flow_result["ignored_slot"] = slot_to_collect
            flow_result["reason"] = "invalid_slot_value"
        else:
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
    started_at = time.perf_counter()
    arguments = _action_arguments(next_action, tracker, metadata)

    register_builtin_actions()
    action_obj = get_action(next_action)
    if action_obj is None:
        next_action = "action_default_fallback"
        action_obj = get_action(next_action)
        arguments = _action_arguments(next_action, tracker, metadata)

    if action_obj is None or tracker is None:
        error_type = "action_not_found" if action_obj is None else "missing_tracker"
        result = ActionResult(text="系统暂时不可用。", metadata={"action": next_action, "error": error_type})
        record_tool_trace(
            tool_name=next_action,
            arguments_json=arguments,
            result_json={
                **result.to_dict(),
                "failure_type": "TOOL_ARGUMENT_ERROR",
                "error_type": error_type,
            },
            status="failed",
            latency_ms=_elapsed_ms(started_at),
        )
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
        record_tool_trace(
            tool_name=next_action,
            arguments_json=arguments,
            result_json={
                **result.to_dict(),
                "failure_type": "TOOL_FAILURE",
                "error_type": exc.__class__.__name__,
            },
            status="failed",
            latency_ms=_elapsed_ms(started_at),
        )
        return {
            **state,
            "error": str(exc),
            "action_result": result.to_dict(),
            "responses": [{"text": result.text or "", "metadata": result.metadata}],
        }

    record_tool_trace(
        tool_name=next_action,
        arguments_json=arguments,
        result_json=result.to_dict(),
        status="success",
        latency_ms=_elapsed_ms(started_at),
    )

    if next_action in {"action_confirm_postsale", "action_show_logistics"}:
        _finish_active_flow(tracker)

    return {
        **state,
        "action_result": result.to_dict(),
        "responses": [{"text": result.text or "", "metadata": result.metadata}],
    }


def tool(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    sender_id = str(state.get("sender_id") or "default")
    classification = _model_dump(state.get("business_classification"))
    tool_name = str(classification.get("target_tool") or "").strip()
    arguments = dict(classification.get("extracted_arguments") or {})

    result = _invoke_business_tool(state, tool_name, arguments)
    result_data = result.to_dict()
    response_text = _tool_success_text(result_data) if result.success else _tool_failure_text(result_data)

    if tracker is not None:
        tracker.latest_action_name = tool_name or "business_tool"

    return {
        **state,
        "route": "tool",
        "tool_result": result_data,
        "responses": [
            {
                "recipient_id": sender_id,
                "text": response_text,
                "metadata": {
                    "source": "tool",
                    "tool_name": result.tool_name,
                    "tool_status": result.status,
                    "tool_success": result.success,
                },
            }
        ],
    }


def ticket(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    sender_id = str(state.get("sender_id") or "default")
    message = str(state.get("message") or "").strip()
    llm_results = state.get("llm_results") or []
    ticket_service = state.get("ticket_service")

    if not isinstance(ticket_service, TicketService):
        ticket_service = TicketService()

    business_classification = _model_dump(state.get("business_classification"))
    if str(business_classification.get("target_tool") or "") == "create_ticket":
        arguments = dict(business_classification.get("extracted_arguments") or {})
        result = _invoke_business_tool(state, "create_ticket", arguments)
        result_data = result.to_dict()
        ticket_result = result_data.get("data") if isinstance(result_data.get("data"), dict) else {}
        response_text = _tool_success_text(result_data) if result.success else _tool_failure_text(result_data)
        if tracker is not None:
            tracker.latest_action_name = "create_ticket"
        return {
            **state,
            "ticket": ticket_result,
            "tool_result": result_data,
            "responses": [
                {
                    "recipient_id": sender_id,
                    "text": response_text,
                    "metadata": {
                        "source": "tool",
                        "tool_name": "create_ticket",
                        "tool_status": result.status,
                        "tool_success": result.success,
                        "ticket_id": ticket_result.get("ticket_id") if isinstance(ticket_result, dict) else None,
                    },
                }
            ],
            "route": "ticket",
        }

    ticket_data = _first_command_data(llm_results, "ticket")
    ticket_text = str(ticket_data.get("text") or message)
    arguments = _ticket_arguments(sender_id=sender_id, ticket_text=ticket_text, ticket_data=ticket_data)
    started_at = time.perf_counter()
    try:
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
    except Exception as exc:
        record_tool_trace(
            tool_name="ticket_create",
            arguments_json=arguments,
            result_json={
                "error": str(exc),
                "failure_type": "TOOL_FAILURE",
                "error_type": exc.__class__.__name__,
            },
            status="failed",
            latency_ms=_elapsed_ms(started_at),
        )
        raise

    if tracker is not None:
        tracker.latest_action_name = "ticket_create"

    response_metadata = {
        "source": "ticket",
        "ticket_id": ticket.ticket_id,
        "category": ticket.category,
        "priority": ticket.priority,
    }
    ticket_result = {
        "ticket_id": ticket.ticket_id,
        "sender_id": ticket.sender_id,
        "title": ticket.title,
        "summary": ticket.summary,
        "category": ticket.category,
        "priority": ticket.priority,
        "suggestion": ticket.suggestion,
        "status": ticket.status,
        "metadata": ticket.metadata,
    }
    record_tool_trace(
        tool_name="ticket_create",
        arguments_json=arguments,
        result_json=ticket_result,
        status="success",
        latency_ms=_elapsed_ms(started_at),
    )

    return {
        **state,
        "ticket": ticket_result,
        "responses": [
            {
                "recipient_id": sender_id,
                "text": "这个问题需要人工进一步确认，我已经帮你生成工单，客服会根据订单信息继续处理。",
                "metadata": response_metadata,
            }
        ],
        "route": "ticket",
    }
