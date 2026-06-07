from __future__ import annotations

import logging
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agent.graph.state import AgentState
from app.agent.tool_safety import (
    PENDING_TOOL_CONFIRMATION_SLOT,
    AgentToolSafetyPolicy,
    fingerprint_tool_call,
    is_cancellation_message,
    is_confirmation_message,
)
from app.persistence.tool_recorder import record_tool_trace
from app.core.tracker import DialogueStateTracker
from app.dialogue.llm_generator import LLMCommandGenerator
from app.dialogue.command_processor import CommandProcessor
from app.dialogue.command_parser import CommandParser
from app.rag.answerer import KnowledgeAnswerer
from app.actions.registry import get_action
from app.actions.base import ActionResult
from app.intent import BusinessQuestionClassifier, IntentClassifier, IntentRoutePolicy, IntentTaxonomy
from app.rag.citation import CitationBuilder
from app.tickets import TicketService
from app.actions.builtin import register_builtin_actions
from app.tools import (
    MockBusinessToolService,
    ToolCallResult,
    ToolError,
    ToolExecutionPolicy,
    get_tool_schema,
    validate_tool_arguments,
)

logger = logging.getLogger(__name__)

DEFAULT_INTENT_TAXONOMY_PATH = Path(__file__).resolve().parents[3] / "data" / "intents" / "customer_intents.yml"


class _DisabledIntentLLMClient:
    enabled = False


@lru_cache(maxsize=1)
def _load_default_intent_taxonomy() -> IntentTaxonomy:
    return IntentTaxonomy.load(DEFAULT_INTENT_TAXONOMY_PATH)


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


def _is_likely_order_id(value: str) -> bool:
    text = value.strip()
    if len(text) < 4 or len(text) > 64:
        return False
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", text):
        return False
    return any(ch.isdigit() for ch in text)


def _build_intent_classifier(state: AgentState) -> Any:
    classifier = state.get("intent_classifier")
    if classifier is not None and hasattr(classifier, "classify"):
        return classifier

    llm_generator = state.get("llm_generator")
    llm_client = getattr(llm_generator, "client", None) or _DisabledIntentLLMClient()
    return IntentClassifier(_load_default_intent_taxonomy(), llm_client=llm_client)


def _build_intent_route_policy(state: AgentState) -> Any:
    policy = state.get("intent_route_policy")
    if policy is not None and hasattr(policy, "decide"):
        return policy
    return IntentRoutePolicy()


def _build_business_question_classifier(state: AgentState) -> Any:
    classifier = state.get("business_classifier")
    if classifier is not None and hasattr(classifier, "classify"):
        return classifier
    return BusinessQuestionClassifier()


def _build_tool_safety_policy(state: AgentState) -> AgentToolSafetyPolicy:
    policy = state.get("tool_safety_policy")
    if isinstance(policy, AgentToolSafetyPolicy):
        return policy
    if isinstance(policy, dict):
        try:
            return AgentToolSafetyPolicy(**policy)
        except TypeError:
            logger.warning("invalid tool safety policy ignored")
    return AgentToolSafetyPolicy()


def _build_business_tool_service(state: AgentState) -> Any:
    service = state.get("business_tool_service")
    if service is not None:
        return service
    policy = _build_tool_safety_policy(state)
    return MockBusinessToolService(
        policy=ToolExecutionPolicy(
            timeout_seconds=policy.tool_timeout_seconds,
            max_retries=policy.max_tool_retries,
            retry_backoff_seconds=policy.retry_backoff_seconds,
        )
    )


def _clear_started_flow(tracker: Any) -> None:
    if tracker is None:
        return

    active_flow = getattr(tracker, "active_flow", None)
    flow_history = getattr(tracker, "flow_history", None)
    if active_flow and isinstance(flow_history, list):
        flow_history.append(
            {
                "flow_name": active_flow,
                "status": "cancelled",
                "reason": "route_policy_override",
            }
        )

    if hasattr(tracker, "active_flow"):
        tracker.active_flow = None
        tracker.flow_status = "idle"
        tracker.flow_step_index = 0
        tracker.slot_to_collect = None
    elif isinstance(tracker, dict):
        tracker["active_flow"] = None
        tracker["flow_status"] = "idle"
        tracker["flow_step_index"] = 0
        tracker["slot_to_collect"] = None


def _tracker_get_slot(tracker: Any, key: str) -> Any | None:
    if tracker is None:
        return None
    if hasattr(tracker, "get_slot"):
        return tracker.get_slot(key)
    if isinstance(tracker, dict):
        slots = tracker.get("slots")
        if isinstance(slots, dict):
            return slots.get(key)
        return tracker.get(key)
    slots = getattr(tracker, "slots", None)
    if isinstance(slots, dict):
        return slots.get(key)
    return None


def _tracker_set_slot(tracker: Any, key: str, value: Any) -> None:
    if tracker is None:
        return
    if hasattr(tracker, "set_slot"):
        tracker.set_slot(key, value)
        return
    if isinstance(tracker, dict):
        tracker.setdefault("slots", {})[key] = value
        return
    slots = getattr(tracker, "slots", None)
    if isinstance(slots, dict):
        slots[key] = value


def _tracker_clear_slot(tracker: Any, key: str) -> None:
    if tracker is None:
        return
    slots = getattr(tracker, "slots", None)
    if isinstance(slots, dict):
        slots.pop(key, None)
        return
    if isinstance(tracker, dict):
        raw_slots = tracker.get("slots")
        if isinstance(raw_slots, dict):
            raw_slots.pop(key, None)
        tracker.pop(key, None)


def _graph_route_from_execution(execution_route: str) -> str:
    if execution_route == "tool":
        return "action"
    return execution_route


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _intent_response_metadata(intent_result: Any, route_decision: Any) -> dict[str, Any]:
    intent_data = _model_dump(intent_result)
    decision_data = _model_dump(route_decision)

    metadata: dict[str, Any] = {}
    intent_id = str(intent_data.get("intent_id") or "").strip()
    if intent_id and intent_id != "UNKNOWN":
        metadata["intentLeafIds"] = [intent_id]
    elif intent_data:
        metadata["intentLeafIds"] = []

    if intent_data:
        metadata["intentSource"] = intent_data.get("source") or "unknown"
        metadata["intentConfidence"] = intent_data.get("confidence")

    if decision_data:
        metadata["execution_route"] = decision_data.get("execution_route")
        metadata["system_route"] = decision_data.get("system_route")
        metadata["route_reason"] = decision_data.get("reason")
        metadata["requires_rag"] = decision_data.get("requires_rag")

    return metadata


def _business_response_metadata(classification: Any) -> dict[str, Any]:
    data = _model_dump(classification)
    if not data:
        return {}

    return {
        "business_question_type": data.get("question_type"),
        "business_route": data.get("route"),
        "business_tool": data.get("target_tool"),
        "business_confidence": data.get("confidence"),
        "business_required_arguments": data.get("required_arguments") or [],
        "business_missing_arguments": data.get("missing_arguments") or [],
        "business_extracted_arguments": data.get("extracted_arguments") or {},
        "business_requires_rag": data.get("requires_rag"),
        "business_requires_confirmation": data.get("requires_confirmation"),
        "business_risk_level": data.get("risk_level"),
        "business_reason": data.get("reason"),
        "business_signals": data.get("signals") or [],
        "business_source": data.get("source"),
    }


def _tool_response_metadata(tool_result: Any) -> dict[str, Any]:
    data = _model_dump(tool_result)
    if not data:
        return {}

    error = data.get("error")
    error_code = error.get("code") if isinstance(error, dict) else None
    result_metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return {
        "tool_name": data.get("tool_name"),
        "tool_success": data.get("success"),
        "tool_status": data.get("status"),
        "tool_arguments": data.get("arguments") or {},
        "tool_error_code": error_code,
        "tool_latency_ms": data.get("latency_ms"),
        "tool_attempt_count": result_metadata.get("attempt_count"),
        "tool_timeout_seconds": result_metadata.get("timeout_seconds"),
    }


def _tool_safety_response_metadata(tool_safety: Any) -> dict[str, Any]:
    data = _model_dump(tool_safety)
    if not data:
        return {}

    return {
        "tool_safety_decision": data.get("decision"),
        "tool_safety_reason": data.get("reason"),
        "pending_tool_name": data.get("tool_name"),
        "pending_tool_arguments": data.get("arguments") or {},
    }


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


def _should_use_business_route(route_name: str | None, route_decision: Any | None) -> bool:
    if route_name is None:
        return False
    if route_name != "rag":
        return True

    decision_data = _model_dump(route_decision)
    execution_route = str(decision_data.get("execution_route") or "").strip()
    return execution_route in {"", "rag", "fallback"}


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


def _finish_active_flow(tracker: Any) -> None:
    active_flow = getattr(tracker, "active_flow", None)
    if not active_flow:
        return

    flow_history = getattr(tracker, "flow_history", None)
    if isinstance(flow_history, list):
        flow_history.append(
            {
                "flow_name": active_flow,
                "status": "finished",
            }
        )
    tracker.active_flow = None
    tracker.flow_status = "idle"
    tracker.flow_step_index = 0
    tracker.slot_to_collect = None


def _rag_response_metadata(
    *,
    route_name: str,
    rewritten_query: str | None,
    rag_matches: list[dict[str, Any]],
    used_llm: bool,
    ticket: dict[str, Any],
) -> dict[str, Any]:
    citation_metadata = CitationBuilder().from_matches(rag_matches)

    metadata = {
        "route": route_name,
        "rag_match_count": len(rag_matches),
        "used_llm": used_llm,
        "ticket_id": ticket.get("ticket_id") if isinstance(ticket, dict) else None,
        **citation_metadata,
    }
    if rewritten_query:
        metadata["rewritten_query"] = rewritten_query
    return metadata


def _merge_response_metadata(responses: list[dict[str, Any]], common: dict[str, Any]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for response in responses:
        item = dict(response)
        metadata = dict(item.get("metadata") or {})
        item["metadata"] = {**metadata, **common}
        merged.append(item)
    return merged


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _tracker_tool_snapshot(tracker: Any) -> dict[str, Any]:
    if tracker is None:
        return {}

    if hasattr(tracker, "to_dict"):
        data = tracker.to_dict()
    elif isinstance(tracker, dict):
        data = dict(tracker)
    else:
        data = {
            "sender_id": getattr(tracker, "sender_id", None),
            "slots": getattr(tracker, "slots", None),
            "active_flow": getattr(tracker, "active_flow", None),
            "flow_status": getattr(tracker, "flow_status", None),
            "slot_to_collect": getattr(tracker, "slot_to_collect", None),
        }

    return {
        "sender_id": data.get("sender_id"),
        "slots": dict(data.get("slots") or {}),
        "active_flow": data.get("active_flow"),
        "flow_status": data.get("flow_status"),
        "slot_to_collect": data.get("slot_to_collect"),
        "latest_action_name": data.get("latest_action_name"),
    }


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


def _get_tool_schema_data(tool_name: str) -> dict[str, Any]:
    try:
        return get_tool_schema(tool_name).model_dump(mode="json")
    except Exception:
        return {}


def _tool_requires_confirmation(tool_name: str, classification: Any, policy: AgentToolSafetyPolicy) -> bool:
    data = _model_dump(classification)
    if bool(data.get("requires_confirmation")):
        return True

    schema = _get_tool_schema_data(tool_name)
    if bool(schema.get("requires_confirmation")):
        return True

    risk_level = str(schema.get("risk_level") or data.get("risk_level") or "low").strip()
    return risk_level in set(policy.high_risk_levels)


def _pending_tool_confirmation(tracker: Any) -> dict[str, Any]:
    pending = _tracker_get_slot(tracker, PENDING_TOOL_CONFIRMATION_SLOT)
    return dict(pending) if isinstance(pending, dict) else {}


def _pending_confirmation_expired(pending: dict[str, Any], policy: AgentToolSafetyPolicy) -> bool:
    created_at = pending.get("created_at")
    if created_at is None:
        return False
    try:
        return (time.time() - float(created_at)) > policy.confirmation_ttl_seconds
    except (TypeError, ValueError):
        return True


def _build_pending_tool_confirmation(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    classification: Any,
    message: str,
) -> dict[str, Any]:
    data = _model_dump(classification)
    schema = _get_tool_schema_data(tool_name)
    risk_level = str(data.get("risk_level") or schema.get("risk_level") or "medium")
    return {
        "tool_name": tool_name,
        "arguments": dict(arguments),
        "fingerprint": fingerprint_tool_call(tool_name, arguments),
        "question_type": data.get("question_type") or "unknown",
        "required_arguments": data.get("required_arguments") or list(arguments.keys()),
        "risk_level": risk_level,
        "source_message": message,
        "created_at": time.time(),
    }


def _business_classification_from_pending(pending: dict[str, Any]) -> dict[str, Any]:
    arguments = dict(pending.get("arguments") or {})
    return {
        "question_type": pending.get("question_type") or "unknown",
        "route": "tool",
        "confidence": 1.0,
        "target_tool": pending.get("tool_name"),
        "required_arguments": pending.get("required_arguments") or list(arguments.keys()),
        "missing_arguments": [],
        "extracted_arguments": arguments,
        "requires_rag": False,
        "requires_confirmation": True,
        "risk_level": pending.get("risk_level") or "medium",
        "signals": ["confirmed_tool_call"],
        "reason": "user confirmed pending high-risk tool call",
        "source": "tool_confirmation",
    }


def _tool_confirmation_reply(pending: dict[str, Any]) -> str:
    tool_name = str(pending.get("tool_name") or "").strip()
    arguments = dict(pending.get("arguments") or {})
    if tool_name == "create_invoice":
        return (
            f"请确认：是否为订单 {arguments.get('order_id')} "
            f"开具抬头为“{arguments.get('title')}”的发票？回复“确认”后我再执行。"
        )
    return f"这个操作需要二次确认。请确认是否执行 {tool_name}：{arguments}？回复“确认”后我再执行。"


def _tool_confirmation_cancel_reply(pending: dict[str, Any]) -> str:
    tool_name = str(pending.get("tool_name") or "业务操作").strip()
    return f"已取消本次 {tool_name} 操作，没有执行工具调用。"


def _router_failed_tool_result(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    started_at: float,
    error: ToolError,
    attempt_count: int,
    metadata: dict[str, Any] | None = None,
) -> ToolCallResult:
    result = ToolCallResult(
        tool_name=tool_name or "unknown",
        success=False,
        status="failed",
        arguments=arguments,
        error=error,
        latency_ms=_elapsed_ms(started_at),
        metadata={
            "source": "tool_router",
            "attempt_count": attempt_count,
            "attempts": [],
            **(metadata or {}),
        },
    )
    record_tool_trace(
        tool_name=result.tool_name,
        arguments_json=result.arguments,
        result_json=result.to_dict(),
        status=result.status,
        latency_ms=result.latency_ms,
    )
    return result


def _check_tool_call_safety(
    state: AgentState,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    started_at: float,
) -> ToolCallResult | None:
    policy = _build_tool_safety_policy(state)
    fingerprint = fingerprint_tool_call(tool_name, arguments)
    fingerprints = state.setdefault("tool_call_fingerprints", [])
    if not isinstance(fingerprints, list):
        fingerprints = []
        state["tool_call_fingerprints"] = fingerprints

    if policy.duplicate_call_detection and fingerprint in fingerprints:
        return _router_failed_tool_result(
            tool_name=tool_name,
            arguments=arguments,
            started_at=started_at,
            error=ToolError(
                code="TOOL_REPEATED_CALL",
                message="Repeated tool call detected.",
                retryable=False,
                details={"fingerprint": fingerprint},
            ),
            attempt_count=0,
            metadata={"safety_reason": "duplicate_tool_call"},
        )

    call_count = int(state.get("tool_call_count") or 0)
    max_calls = max(1, int(policy.max_tool_calls_per_turn))
    if call_count >= max_calls:
        return _router_failed_tool_result(
            tool_name=tool_name,
            arguments=arguments,
            started_at=started_at,
            error=ToolError(
                code="TOOL_CALL_LIMIT_EXCEEDED",
                message="Maximum tool calls per turn exceeded.",
                retryable=False,
                details={"max_tool_calls_per_turn": max_calls},
            ),
            attempt_count=0,
            metadata={"safety_reason": "max_tool_calls_per_turn"},
        )

    fingerprints.append(fingerprint)
    state["tool_call_count"] = call_count + 1
    return None


def _invoke_business_tool(state: AgentState, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
    started_at = time.perf_counter()
    try:
        parsed_arguments = validate_tool_arguments(tool_name, arguments)
    except Exception as exc:
        return _router_failed_tool_result(
            tool_name=tool_name or "unknown",
            arguments=dict(arguments),
            started_at=started_at,
            error=ToolError(
                code="TOOL_ARGUMENT_ERROR",
                message="Tool arguments do not match schema.",
                retryable=False,
                details={"error": str(exc)},
            ),
            attempt_count=0,
        )

    safety_result = _check_tool_call_safety(
        state,
        tool_name=tool_name,
        arguments=parsed_arguments,
        started_at=started_at,
    )
    if safety_result is not None:
        return safety_result

    service = _build_business_tool_service(state)
    method = getattr(service, tool_name, None)
    if method is None or not callable(method):
        return _router_failed_tool_result(
            tool_name=tool_name or "unknown",
            arguments=parsed_arguments,
            started_at=started_at,
            error=ToolError(
                code="TOOL_NOT_FOUND",
                message=f"Business tool is not registered: {tool_name}",
                retryable=False,
            ),
            attempt_count=0,
        )

    try:
        result = method(**parsed_arguments)
    except Exception as exc:
        logger.exception("business tool invocation failed: %s", exc)
        return _router_failed_tool_result(
            tool_name=tool_name,
            arguments=parsed_arguments,
            started_at=started_at,
            error=ToolError(
                code="TOOL_FAILURE",
                message=str(exc) or exc.__class__.__name__,
                retryable=False,
                details={"error_type": exc.__class__.__name__},
            ),
            attempt_count=1,
        )

    if isinstance(result, ToolCallResult):
        return result
    if hasattr(result, "model_validate"):
        return ToolCallResult.model_validate(result)
    if isinstance(result, dict):
        return ToolCallResult.model_validate(result)
    return _router_failed_tool_result(
        tool_name=tool_name,
        arguments=parsed_arguments,
        started_at=started_at,
        error=ToolError(
            code="TOOL_RETURN_ERROR",
            message="Business tool returned an unsupported result type.",
            retryable=False,
            details={"result_type": result.__class__.__name__},
        ),
        attempt_count=1,
    )


def _tool_success_text(result: dict[str, Any]) -> str:
    tool_name = str(result.get("tool_name") or "").strip()
    data = result.get("data") if isinstance(result.get("data"), dict) else {}

    if tool_name == "query_order":
        items = data.get("items") if isinstance(data.get("items"), list) else []
        item_names = "、".join(str(item.get("name")) for item in items if isinstance(item, dict) and item.get("name"))
        return (
            f"订单 {data.get('order_id')} 当前状态：{data.get('status')}，"
            f"支付状态：{data.get('payment_status')}，金额：{data.get('total_amount')} {data.get('currency')}。"
            + (f"商品：{item_names}。" if item_names else "")
        )

    if tool_name == "query_logistics":
        return (
            f"订单 {data.get('order_id')} 当前物流状态：{data.get('status')}，"
            f"承运商：{data.get('carrier')}，运单号：{data.get('tracking_no')}，"
            f"当前位置：{data.get('current_location')}，预计送达：{data.get('estimated_delivery')}。"
        )

    if tool_name == "create_ticket":
        return f"已为你创建工单 {data.get('ticket_id')}，当前状态：{data.get('status')}，优先级：{data.get('priority')}。"

    if tool_name == "create_invoice":
        return (
            f"已为订单 {data.get('order_id')} 创建电子发票，"
            f"发票号：{data.get('invoice_id')}，抬头：{data.get('title')}。"
        )

    return "业务工具已执行完成。"


def _tool_failure_text(result: dict[str, Any]) -> str:
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    code = str(error.get("code") or "TOOL_FAILURE")
    if code == "TOOL_TIMEOUT":
        return "业务系统响应超时，我已经记录这次调用信息，稍后可以转人工继续处理。"
    if code == "TOOL_EMPTY_RESULT":
        return "我暂时没有查到可用结果，已经记录这次调用信息，稍后可以转人工继续处理。"
    if code == "TOOL_REPEATED_CALL":
        return "检测到重复的工具调用。为避免重复处理，我已经停止执行本次工具调用。"
    if code == "TOOL_CALL_LIMIT_EXCEEDED":
        return "本轮工具调用次数已达到安全上限。为避免重复执行，我已经停止继续调用工具。"
    if code == "ORDER_NOT_FOUND":
        return "我没有查到这个订单，请确认订单号是否正确。"
    if code == "LOGISTICS_NOT_FOUND":
        return "我暂时没有查到该订单的物流信息，可能还未发货或物流暂未同步。"
    if code == "ORDER_NOT_INVOICEABLE":
        return "这个订单当前暂时不能开票，请确认订单是否已支付完成。"
    if code == "TOOL_ARGUMENT_ERROR":
        return "你提供的信息还不完整或格式不正确，请补充后我再继续处理。"
    return "业务工具暂时不可用，我已经记录这次调用信息，稍后可以转人工继续处理。"


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
    intent_result = _classify_intent(state, message)
    business_classification = _classify_business_question(state, message, tracker, intent_result)

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

    if _should_use_business_route(business_route_name, route_decision):
        route_name = business_route_name
        if route_name != "flow" and _has_command_type(results, "start_flow"):
            _clear_started_flow(tracker)
        if route_name == "clarify" and not reply_text:
            reply_text = _business_clarify_reply(business_classification)
    elif (
        route_decision is not None
        and intent_result is not None
        and getattr(intent_result, "intent_id", None) != "UNKNOWN"
        and not _has_command_type(results, "set_slot")
    ):
        route_name = _graph_route_from_execution(str(route_decision.execution_route))
        if route_name != "flow" and _has_command_type(results, "start_flow"):
            _clear_started_flow(tracker)
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


def rag(state: AgentState) -> AgentState:
    results = state.get("llm_results") or []
    message = str(state.get("message") or "").strip()
    knowledge_answerer = state.get("knowledge_answerer")

    if not isinstance(knowledge_answerer, KnowledgeAnswerer):
        knowledge_answerer = KnowledgeAnswerer()

    command_data = _first_command_data(results, "knowledge_answer")
    rag_query = str(command_data.get("query") or message)
    top_k = int(command_data.get("top_k") or 3)
    intent_data = _model_dump(state.get("intent_result"))
    intent_id = str(intent_data.get("intent_id") or "").strip()
    if intent_id == "UNKNOWN":
        intent_id = ""

    try:
        answer = knowledge_answerer.answer(rag_query, top_k=top_k, intent_id=intent_id or None)
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


def generate_response(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    sender_id = str(state.get("sender_id") or "default")
    reply_text = str(state.get("reply_text") or "").strip()
    responses = list(state.get("responses") or [])
    action_result = state.get("action_result") or {}
    tool_result = state.get("tool_result") or {}
    ticket = state.get("ticket") or {}
    route_name = str(state.get("route") or "fallback")
    rag_matches = state.get("rag_matches") or []
    knowledge_answer = str(state.get("knowledge_answer") or "")
    error = str(state.get("error") or "")
    common_metadata = _rag_response_metadata(
        route_name=route_name,
        rewritten_query=str(state.get("rag_query") or "").strip() or None,
        rag_matches=rag_matches,
        used_llm=bool(state.get("used_llm")),
        ticket=ticket if isinstance(ticket, dict) else {},
    )
    common_metadata.update(_intent_response_metadata(state.get("intent_result"), state.get("route_decision")))
    common_metadata.update(_business_response_metadata(state.get("business_classification")))
    common_metadata.update(_tool_response_metadata(tool_result))
    common_metadata.update(_tool_safety_response_metadata(state.get("tool_safety")))

    if reply_text and route_name in {"chitchat", "clarify"}:
        responses = [
            {
                "recipient_id": sender_id,
                "text": reply_text,
                "metadata": {"source": "llm" if route_name == "chitchat" else "business_router", "command_type": route_name},
            }
        ]

    if tracker is not None and responses:
        final_text = str(responses[0].get("text") or "")
        tracker.add_bot_message(final_text)
        tracker.latest_action_name = str(
            action_result.get("metadata", {}).get("action")
            or tool_result.get("tool_name")
            or tracker.latest_action_name
            or route_name
        )

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
                    "error": error or None,
                    **(action_result.get("metadata") or {}),
                },
            }
        ]
        if tracker is not None:
            tracker.add_bot_message(fallback_text)

    final_responses = _merge_response_metadata(final_responses, common_metadata)

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
