from __future__ import annotations

import logging
import time
from typing import Any

from app.agent.graph.state import AgentState
from app.agent.graph.node_services import _build_business_tool_service, _build_tool_safety_policy
from app.agent.graph.node_shared import _elapsed_ms, _model_dump
from app.agent.graph.node_tracker import _tracker_get_slot
from app.agent.tool_safety import AgentToolSafetyPolicy, PENDING_TOOL_CONFIRMATION_SLOT, fingerprint_tool_call
from app.persistence.tool_recorder import record_tool_trace
from app.tools import ToolCallResult, ToolError, get_tool_schema, validate_tool_arguments

logger = logging.getLogger(__name__)


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
