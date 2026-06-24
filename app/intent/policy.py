from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from .schema import ExecutionRoute, IntentResult


class RouteDecision(BaseModel):
    execution_route: ExecutionRoute
    system_route: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    requires_rag: bool = False


class IntentRoutePolicy:
    """Decide the execution route from a classified intent."""

    def decide(
        self,
        intent_result: IntentResult,
        message: str,
        tracker: Any | None = None,
    ) -> RouteDecision:
        text = message.strip()
        intent_id = intent_result.intent_id
        intent_type = intent_result.intent_type
        candidate_ids = _candidate_ids(intent_result)

        if intent_result.needs_clarification:
            return RouteDecision(
                execution_route="clarify",
                system_route="clarify",
                reason=intent_result.clarify_reason or "意图置信度不足，需要澄清",
                requires_rag=False,
            )

        if intent_id == "UNKNOWN" or intent_type == "UNKNOWN":
            return RouteDecision(
                execution_route="fallback",
                system_route="unknown",
                reason="意图不明确，先追问用户具体需求，不触发知识库检索",
                requires_rag=False,
            )

        if intent_id == "C1_寒暄问候":
            return RouteDecision(
                execution_route="chitchat",
                system_route="chitchat",
                reason="用户是问候或客套交流，直接闲聊回应",
                requires_rag=False,
            )

        if intent_id == "C2_越界提问":
            return RouteDecision(
                execution_route="chitchat",
                system_route="out_of_scope",
                reason="问题超出售后客服业务范围，礼貌说明服务边界，不触发 RAG",
                requires_rag=False,
            )

        contract_decision = _contract_route_decision(intent_result)
        if contract_decision is not None:
            return contract_decision

        if intent_id == "F2_功能建议":
            return RouteDecision(
                execution_route="ticket",
                system_route="ticket",
                reason="功能建议应记录反馈或生成工单，不需要知识库检索",
                requires_rag=False,
            )

        if intent_id == "F3_投诉吐槽":
            if _has_fact_context(text, candidate_ids):
                return RouteDecision(
                    execution_route="rag",
                    system_route="kb_ticket",
                    reason="投诉中包含物流或故障事实，先走 RAG 给出基础规则/排查，再引导人工处理",
                    requires_rag=True,
                )
            return RouteDecision(
                execution_route="ticket",
                system_route="ticket",
                reason="纯投诉或负向反馈优先生成工单，不直接进入售后流程索要订单号",
                requires_rag=False,
            )

        if intent_id == "F1_故障报告":
            return RouteDecision(
                execution_route="rag",
                system_route="kb_ticket",
                reason="故障问题先走 RAG 给基础排查步骤，再引导创建工单，不直接索要订单号",
                requires_rag=True,
            )

        if intent_id == "S15_退换货":
            return _rag_first_decision(
                system_route="kb_tool",
                has_order_id=_has_order_id(text, tracker),
                reason_without_order="退换货问题先回答政策和申请规则，再引导用户提供订单信息",
                reason_with_order="退换货问题已包含订单信息；第一版仍先走 RAG 回答规则，后续可升级为工具或流程",
            )

        if intent_id == "S16_物流配送":
            return _rag_first_decision(
                system_route="kb_tool",
                has_order_id=_has_order_id(text, tracker),
                reason_without_order="物流配送问题先回答发货、改地址或配送规则，避免直接进入订单号流程",
                reason_with_order="物流配送问题已包含订单信息；第一版仍先走 RAG 回答规则，后续可升级为物流工具",
            )

        service_number = _service_intent_number(intent_id)
        if service_number is not None and (1 <= service_number <= 14 or service_number == 17):
            system_route = _system_route_for_intent_type(intent_type)
            return RouteDecision(
                execution_route="rag",
                system_route=system_route,
                reason=f"{intent_result.intent_name}属于知识或政策咨询，走 RAG 检索知识库后回答",
                requires_rag=True,
            )

        if intent_type == "KB":
            return RouteDecision(
                execution_route="rag",
                system_route="kb",
                reason="知识问答类意图，走 RAG 检索知识库后回答",
                requires_rag=True,
            )

        if intent_type == "KB_TOOL":
            return RouteDecision(
                execution_route="rag",
                system_route="kb_tool",
                reason="知识加工具类意图，第一版先走 RAG 回答规则，再引导工具能力",
                requires_rag=True,
            )

        if intent_type == "KB_TICKET":
            return RouteDecision(
                execution_route="rag",
                system_route="kb_ticket",
                reason="知识加工单类意图，先走 RAG 给出基础说明，再引导人工处理",
                requires_rag=True,
            )

        if intent_type == "TOOL":
            return RouteDecision(
                execution_route="tool",
                system_route="tool",
                reason="该意图需要业务系统查询，交给工具链路处理",
                requires_rag=False,
            )

        if intent_type == "TICKET":
            return RouteDecision(
                execution_route="ticket",
                system_route="ticket",
                reason="该意图需要记录反馈或人工处理，不触发 RAG",
                requires_rag=False,
            )

        if intent_type == "FLOW":
            return RouteDecision(
                execution_route="flow",
                system_route="flow",
                reason="该意图需要多轮槽位收集，进入流程链路",
                requires_rag=False,
            )

        if intent_type == "CHITCHAT":
            return RouteDecision(
                execution_route="chitchat",
                system_route="chitchat",
                reason="闲聊类意图，直接生成轻量回复",
                requires_rag=False,
            )

        return RouteDecision(
            execution_route="fallback",
            system_route="unknown",
            reason="未命中明确路由策略，进入兜底追问",
            requires_rag=False,
        )


def _contract_route_decision(intent_result: IntentResult) -> RouteDecision | None:
    execution_route = intent_result.route or _route_for_kind(intent_result)
    if not execution_route:
        return None

    system_route = _system_route_for_contract(intent_result, execution_route)
    return RouteDecision(
        execution_route=execution_route,
        system_route=system_route,
        reason=f"{intent_result.intent_name}由意图树路由契约指定为 {execution_route}",
        requires_rag=execution_route == "rag",
    )


def _route_for_kind(intent_result: IntentResult) -> ExecutionRoute | None:
    kind = str(intent_result.intent_kind or "").strip()
    if kind == "KB":
        return "rag"
    if kind in {"MCP", "TOOL"}:
        return "tool"
    if kind == "TICKET":
        return "ticket"
    if kind == "SYSTEM":
        return "system_response"
    if kind == "FLOW":
        return "flow"
    if kind == "CHITCHAT":
        return "chitchat"
    return None


def _system_route_for_contract(intent_result: IntentResult, execution_route: ExecutionRoute) -> str:
    if execution_route == "rag":
        return _system_route_for_intent_type(intent_result.intent_type)
    if execution_route == "tool":
        return "tool"
    if execution_route == "ticket":
        return "ticket"
    if execution_route == "flow":
        return "flow"
    if execution_route in {"chitchat", "system_response"}:
        return "chitchat"
    if execution_route == "clarify":
        return "clarify"
    return "unknown"


def _rag_first_decision(
    *,
    system_route: str,
    has_order_id: bool,
    reason_without_order: str,
    reason_with_order: str,
) -> RouteDecision:
    return RouteDecision(
        execution_route="rag",
        system_route=system_route,
        reason=reason_with_order if has_order_id else reason_without_order,
        requires_rag=True,
    )


def _candidate_ids(intent_result: IntentResult) -> set[str]:
    return {candidate.intent_id for candidate in intent_result.candidates}


def _has_fact_context(text: str, candidate_ids: set[str]) -> bool:
    if {"S16_物流配送", "F1_故障报告"} & candidate_ids:
        return True
    return _contains_any(text, LOGISTICS_FACT_KEYWORDS) or _contains_any(text, FAULT_FACT_KEYWORDS)


def _has_order_id(text: str, tracker: Any | None) -> bool:
    slot_value = _get_tracker_slot(tracker, "order_id")
    if slot_value is not None and _looks_like_order_id(str(slot_value)):
        return True
    return any(_looks_like_order_id(match.group(0)) for match in ORDER_ID_RE.finditer(text))


def _get_tracker_slot(tracker: Any | None, key: str) -> Any | None:
    if tracker is None:
        return None
    if hasattr(tracker, "get_slot"):
        return tracker.get_slot(key)
    if isinstance(tracker, dict):
        slots = tracker.get("slots")
        if isinstance(slots, dict):
            return slots.get(key)
        return tracker.get(key)
    return None


def _looks_like_order_id(value: str) -> bool:
    text = value.strip()
    if len(text) < 4 or len(text) > 64:
        return False
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", text):
        return False
    return any(ch.isdigit() for ch in text)


def _service_intent_number(intent_id: str) -> int | None:
    match = re.match(r"S(\d+)_", intent_id)
    if not match:
        return None
    return int(match.group(1))


def _system_route_for_intent_type(intent_type: str) -> str:
    if intent_type == "KB_TOOL":
        return "kb_tool"
    if intent_type == "KB_TICKET":
        return "kb_ticket"
    if intent_type == "TOOL":
        return "tool"
    if intent_type == "TICKET":
        return "ticket"
    if intent_type == "FLOW":
        return "flow"
    if intent_type == "CHITCHAT":
        return "chitchat"
    return "kb"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = text.casefold()
    return any(keyword.casefold() in normalized for keyword in keywords)


ORDER_ID_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9][A-Za-z0-9_-]{3,63}(?![A-Za-z0-9_-])")

LOGISTICS_FACT_KEYWORDS = (
    "物流",
    "快递",
    "发货",
    "配送",
    "改地址",
    "收货地址",
    "签收",
    "到货",
    "送到",
    "包裹",
)

FAULT_FACT_KEYWORDS = (
    "充不进电",
    "不开机",
    "发烫",
    "故障",
    "异常",
    "报错",
    "不工作",
    "坏了",
    "无法使用",
)
