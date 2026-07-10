from __future__ import annotations

import logging
from typing import Any

from app.agent.graph.state import AgentState
from app.agent.graph.node_services import _build_intent_route_policy, _build_tool_safety_policy
from app.agent.graph.node_shared import _has_command_type, _model_dump
from app.agent.graph.node_tooling import (
    _build_pending_tool_confirmation,
    _business_classification_from_pending,
    _pending_confirmation_expired,
    _pending_tool_confirmation,
    _tool_confirmation_cancel_reply,
    _tool_confirmation_reply,
    _tool_requires_confirmation,
)
from app.agent.graph.node_tracker import _clear_started_flow, _tracker_clear_slot, _tracker_set_slot
from app.agent.tool_safety import PENDING_TOOL_CONFIRMATION_SLOT, is_cancellation_message, is_confirmation_message

logger = logging.getLogger(__name__)

READ_ONLY_BUSINESS_TOOLS = {
    "order_query": "query_order",
    "logistics_query": "query_logistics",
    "ticket_status_query": "query_ticket_status",
}


def _graph_route_from_execution(execution_route: str) -> str:
    if execution_route == "tool":
        return "action"
    if execution_route == "system_response":
        return "chitchat"
    return execution_route


def _policy_chitchat_reply(route_decision: Any) -> str:
    decision_data = _model_dump(route_decision)
    if decision_data.get("system_route") == "out_of_scope":
        return "抱歉，我主要处理比特严选的商品、订单、物流和售后问题，这类问题暂时无法回答。"
    return "您好！我是智能客服，请问有什么可以帮您？"


def _business_clarify_reply(classification: Any) -> str:
    data = _model_dump(classification)
    missing = [str(item) for item in data.get("missing_arguments") or []]
    tool_name = str(data.get("target_tool") or "").strip()

    if "order_id" in missing:
        return "请提供订单号，我才能继续帮你查询或办理。"
    if "title" in missing:
        return "请提供发票抬头，例如公司名称或个人抬头。"
    if "user_id" in missing and tool_name == "create_ticket":
        return "请提供用户 ID，我才能帮你创建工单。"
    if missing:
        return f"还缺少这些信息：{', '.join(missing)}。请补充后我再继续处理。"
    return "请补充一下具体信息，我再继续处理。"


def _intent_clarify_reply(intent_result: Any) -> str:
    data = _model_dump(intent_result)
    question = str(data.get("clarify_question") or "").strip()
    if question:
        return question
    return "我还不太确定你的具体需求，可以补充一下你想咨询的问题吗？"


def _business_route_name(classification: Any, *, has_set_slot: bool) -> str | None:
    if has_set_slot:
        return None

    data = _model_dump(classification)
    route_name = str(data.get("route") or "").strip()
    target_tool = str(data.get("target_tool") or "").strip()

    if route_name == "tool" and target_tool:
        return "tool"
    if route_name == "ticket" and target_tool == "create_ticket":
        return "ticket"
    if route_name == "clarify":
        return "clarify"
    if route_name == "rag":
        return "rag"
    return None


def _is_complete_read_only_business_tool(classification: Any) -> bool:
    data = _model_dump(classification)
    question_type = str(data.get("question_type") or "").strip()
    target_tool = str(data.get("target_tool") or "").strip()
    expected_tool = READ_ONLY_BUSINESS_TOOLS.get(question_type)
    required_arguments = {
        str(item).strip()
        for item in data.get("required_arguments") or []
        if str(item).strip()
    }
    extracted_arguments = data.get("extracted_arguments")
    if not isinstance(extracted_arguments, dict):
        extracted_arguments = {}

    return (
        str(data.get("route") or "").strip() == "tool"
        and expected_tool is not None
        and target_tool == expected_tool
        and str(data.get("risk_level") or "low").strip() == "low"
        and not bool(data.get("requires_confirmation"))
        and not list(data.get("missing_arguments") or [])
        and bool(required_arguments)
        and all(str(extracted_arguments.get(name) or "").strip() for name in required_arguments)
    )


def _should_use_business_route(
    route_name: str | None,
    route_decision: Any | None,
    business_classification: Any | None = None,
) -> bool:
    if route_name is None:
        return False

    decision_data = _model_dump(route_decision)
    execution_route = str(decision_data.get("execution_route") or "").strip()
    if execution_route in {"", "fallback"}:
        return True
    if route_name == "clarify" and execution_route in {"clarify", "tool", "flow"}:
        return True
    if route_name == "rag" and execution_route == "rag":
        return True
    if (
        route_name == "tool"
        and execution_route == "rag"
        and _is_complete_read_only_business_tool(business_classification)
    ):
        return True
    if route_name == "tool" and execution_route == "tool":
        return True
    if route_name == "ticket" and execution_route == "ticket":
        return True
    if route_name == "flow" and execution_route == "flow":
        return True
    return False


def _should_use_intent_route_decision(
    route_decision: Any | None,
    intent_result: Any | None,
    results: list[dict[str, Any]],
) -> bool:
    if route_decision is None or intent_result is None:
        return False
    if _has_command_type(results, "set_slot"):
        return False

    decision_data = _model_dump(route_decision)
    execution_route = str(decision_data.get("execution_route") or "").strip()
    if execution_route == "clarify":
        return True

    intent_data = _model_dump(intent_result)
    if str(intent_data.get("clarify_reason") or "").strip() == "low_confidence":
        return False
    return str(intent_data.get("intent_id") or "").strip() != "UNKNOWN"


def _is_unknown_or_fallback_route_decision(route_decision: Any | None) -> bool:
    decision_data = _model_dump(route_decision)
    system_route = str(decision_data.get("system_route") or "").strip()
    execution_route = str(decision_data.get("execution_route") or "").strip()
    return system_route in {"", "unknown"} or execution_route in {"", "fallback"}


def route(state: AgentState) -> AgentState:
    llm_result = state.get("llm_result") or {}
    results = state.get("llm_results") or []
    reply_text = str(state.get("reply_text") or "").strip()
    message = str(state.get("message") or "").strip()
    tracker = state.get("tracker")
    active_flow = getattr(tracker, "active_flow", None) if tracker is not None else None
    llm_generator = state.get("llm_generator")
    llm_enabled = bool(getattr(llm_generator, "enabled", False)) if llm_generator is not None else False
    intent_result: Any | None = state.get("intent_result")
    business_classification: Any | None = state.get("business_classification")
    route_decision: Any | None = None
    tool_safety_policy = _build_tool_safety_policy(state)
    tool_safety: dict[str, Any] = {}

    if intent_result is not None:
        try:
            route_decision = _build_intent_route_policy(state).decide(intent_result, message, tracker)
        except Exception as exc:
            logger.exception("intent route policy failed: %s", exc)
            route_decision = None

    pending_confirmation = _pending_tool_confirmation(tracker)
    if pending_confirmation and _pending_confirmation_expired(pending_confirmation, tool_safety_policy):
        _tracker_clear_slot(tracker, PENDING_TOOL_CONFIRMATION_SLOT)
        pending_confirmation = {}

    if pending_confirmation and is_cancellation_message(message, tool_safety_policy):
        _tracker_clear_slot(tracker, PENDING_TOOL_CONFIRMATION_SLOT)
        reply_text = _tool_confirmation_cancel_reply(pending_confirmation)
        return {
            **state,
            "route": "clarify",
            "reply_text": reply_text,
            "intent_result": _model_dump(intent_result),
            "route_decision": _model_dump(route_decision),
            "business_classification": _model_dump(business_classification),
            "tool_safety": {
                "decision": "confirmation_cancelled",
                "reason": "user_cancelled_pending_tool",
                "tool_name": pending_confirmation.get("tool_name"),
                "arguments": pending_confirmation.get("arguments") or {},
            },
        }

    if pending_confirmation and is_confirmation_message(message, tool_safety_policy):
        business_classification = _business_classification_from_pending(pending_confirmation)
        _tracker_clear_slot(tracker, PENDING_TOOL_CONFIRMATION_SLOT)
        tool_safety = {
            "decision": "confirmed",
            "reason": "user_confirmed_pending_tool",
            "tool_name": pending_confirmation.get("tool_name"),
            "arguments": pending_confirmation.get("arguments") or {},
        }

    business_route_name = _business_route_name(
        business_classification,
        has_set_slot=_has_command_type(results, "set_slot"),
    )
    if (
        business_route_name == "rag"
        and _has_command_type(results, "start_flow")
        and _is_unknown_or_fallback_route_decision(route_decision)
    ):
        business_route_name = None

    if business_route_name == "tool":
        classification_data = _model_dump(business_classification)
        candidate_tool = str(classification_data.get("target_tool") or "").strip()
        candidate_arguments = dict(classification_data.get("extracted_arguments") or {})
        if tool_safety.get("decision") != "confirmed" and _tool_requires_confirmation(
            candidate_tool,
            business_classification,
            tool_safety_policy,
        ):
            pending = _build_pending_tool_confirmation(
                tool_name=candidate_tool,
                arguments=candidate_arguments,
                classification=business_classification,
                message=message,
            )
            _tracker_set_slot(tracker, PENDING_TOOL_CONFIRMATION_SLOT, pending)
            return {
                **state,
                "route": "clarify",
                "reply_text": _tool_confirmation_reply(pending),
                "intent_result": _model_dump(intent_result),
                "route_decision": _model_dump(route_decision),
                "business_classification": _model_dump(business_classification),
                "tool_safety": {
                    "decision": "confirmation_required",
                    "reason": "high_risk_tool_requires_confirmation",
                    "tool_name": candidate_tool,
                    "arguments": candidate_arguments,
                },
            }

    if (
        tool_safety.get("decision") == "confirmed"
        and business_route_name == "tool"
    ) or _should_use_business_route(
        business_route_name,
        route_decision,
        business_classification,
    ):
        route_name = business_route_name
        if route_name != "flow" and _has_command_type(results, "start_flow"):
            _clear_started_flow(tracker)
        if route_name == "clarify" and not reply_text:
            reply_text = _business_clarify_reply(business_classification)
    elif _should_use_intent_route_decision(route_decision, intent_result, results):
        route_name = _graph_route_from_execution(str(route_decision.execution_route))
        if route_name != "flow" and _has_command_type(results, "start_flow"):
            _clear_started_flow(tracker)
        if route_name == "clarify" and not reply_text:
            reply_text = _intent_clarify_reply(intent_result)
    elif _has_command_type(results, "ticket"):
        route_name = "ticket"
    elif _has_command_type(results, "knowledge_answer"):
        route_name = "rag"
    elif _has_command_type(results, "chitchat") and reply_text:
        route_name = "chitchat"
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

    if route_decision is not None and route_name == "chitchat" and not reply_text:
        reply_text = _policy_chitchat_reply(route_decision)

    return {
        **state,
        "route": route_name,
        "reply_text": reply_text,
        "intent_result": _model_dump(intent_result),
        "route_decision": _model_dump(route_decision),
        "business_classification": _model_dump(business_classification),
        "tool_safety": tool_safety,
    }
