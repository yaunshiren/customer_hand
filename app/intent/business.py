from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field


BusinessQuestionType = Literal[
    "policy",
    "order_query",
    "logistics_query",
    "complaint",
    "invoice_policy",
    "invoice_create",
    "ticket_status_query",
    "unknown",
]
BusinessRoute = Literal["rag", "tool", "ticket", "clarify", "fallback"]
BusinessToolName = Literal[
    "query_order",
    "query_logistics",
    "create_ticket",
    "query_ticket_status",
    "create_invoice",
]
RiskLevel = Literal["low", "medium", "high"]


class BusinessQuestionClassification(BaseModel):
    question_type: BusinessQuestionType
    route: BusinessRoute
    confidence: float = Field(ge=0.0, le=1.0)
    target_tool: BusinessToolName | None = None
    required_arguments: list[str] = Field(default_factory=list)
    missing_arguments: list[str] = Field(default_factory=list)
    extracted_arguments: dict[str, str] = Field(default_factory=dict)
    requires_rag: bool = False
    requires_confirmation: bool = False
    risk_level: RiskLevel = "low"
    signals: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    source: str = "rule_business_classifier"


class BusinessQuestionClassifier:
    """Classify the request into RAG, tool, ticket, or clarification intent.

    This layer is deliberately deterministic. It is the contract that later tool
    calling can trust before any actual business action is invoked.
    """

    def classify(
        self,
        text: str,
        *,
        intent_result: Any | None = None,
        tracker: Any | None = None,
        user_id: str | None = None,
    ) -> BusinessQuestionClassification:
        original = text.strip()
        normalized = _normalize_text(original)
        intent_id = _intent_id(intent_result)
        intent_type = _intent_type(intent_result)
        order_id = _extract_order_id(normalized, tracker)
        invoice_title = _extract_invoice_title(normalized)
        ticket_no = _extract_ticket_no(normalized)

        if ticket_no and _is_ticket_status_query(normalized):
            return _result(
                question_type="ticket_status_query",
                route="tool",
                confidence=0.96,
                target_tool="query_ticket_status",
                required_arguments=["ticket_no"],
                extracted_arguments={"ticket_no": ticket_no},
                signals=_signals(normalized, intent_id, "ticket_status_query"),
                reason="explicit ticket number and status intent can query ticket persistence",
            )

        if _is_complaint(normalized, intent_id):
            args = {
                "category": "complaint",
                "description": original,
            }
            missing = []
            if user_id:
                args["user_id"] = user_id
            else:
                missing.append("user_id")
            return _result(
                question_type="complaint",
                route="ticket",
                confidence=0.95,
                target_tool="create_ticket",
                required_arguments=["category", "description", "user_id"],
                missing_arguments=missing,
                extracted_arguments=args,
                signals=_signals(normalized, intent_id, "complaint"),
                reason="complaint requests should create a service ticket instead of using RAG",
            )

        if _is_invoice(normalized, intent_id):
            if _is_invoice_policy(normalized, order_id):
                return _result(
                    question_type="invoice_policy",
                    route="rag",
                    confidence=0.88,
                    requires_rag=True,
                    signals=_signals(normalized, intent_id, "invoice_policy"),
                    reason="invoice process or policy question should be answered by RAG",
                )

            extracted = _compact_args(order_id=order_id, title=invoice_title)
            missing = _missing_arguments({"order_id": order_id, "title": invoice_title}, ("order_id", "title"))
            return _result(
                question_type="invoice_create",
                route="tool" if not missing else "clarify",
                confidence=0.92 if not missing else 0.84,
                target_tool="create_invoice",
                required_arguments=["order_id", "title"],
                missing_arguments=missing,
                extracted_arguments=extracted,
                requires_confirmation=not missing,
                risk_level="medium",
                signals=_signals(normalized, intent_id, "invoice_create"),
                reason=(
                    "invoice creation has enough arguments and should be handed to create_invoice"
                    if not missing
                    else "invoice creation is missing required arguments"
                ),
            )

        if _is_logistics_query(normalized, intent_id):
            if order_id:
                return _result(
                    question_type="logistics_query",
                    route="tool",
                    confidence=0.93,
                    target_tool="query_logistics",
                    required_arguments=["order_id"],
                    extracted_arguments={"order_id": order_id},
                    signals=_signals(normalized, intent_id, "logistics_query"),
                    reason="personal logistics query contains an order id and can call query_logistics",
                )
            if _is_personal_order_request(normalized):
                return _result(
                    question_type="logistics_query",
                    route="clarify",
                    confidence=0.85,
                    target_tool="query_logistics",
                    required_arguments=["order_id"],
                    missing_arguments=["order_id"],
                    signals=_signals(normalized, intent_id, "logistics_query"),
                    reason="personal logistics query is missing order_id",
                )
            return _result(
                question_type="policy",
                route="rag",
                confidence=0.8,
                requires_rag=True,
                signals=_signals(normalized, intent_id, "logistics_policy"),
                reason="general logistics rule question should use RAG",
            )

        if _is_order_query(normalized, intent_id):
            if order_id:
                return _result(
                    question_type="order_query",
                    route="tool",
                    confidence=0.92,
                    target_tool="query_order",
                    required_arguments=["order_id"],
                    extracted_arguments={"order_id": order_id},
                    signals=_signals(normalized, intent_id, "order_query"),
                    reason="personal order query contains an order id and can call query_order",
                )
            if _is_personal_order_request(normalized):
                return _result(
                    question_type="order_query",
                    route="clarify",
                    confidence=0.84,
                    target_tool="query_order",
                    required_arguments=["order_id"],
                    missing_arguments=["order_id"],
                    signals=_signals(normalized, intent_id, "order_query"),
                    reason="personal order query is missing order_id",
                )
            return _result(
                question_type="policy",
                route="rag",
                confidence=0.78,
                requires_rag=True,
                signals=_signals(normalized, intent_id, "order_policy"),
                reason="general order rule question should use RAG",
            )

        if _is_policy_question(normalized, intent_type):
            return _result(
                question_type="policy",
                route="rag",
                confidence=0.76,
                requires_rag=True,
                signals=_signals(normalized, intent_id, "policy"),
                reason="knowledge or policy question should use RAG",
            )

        return _result(
            question_type="unknown",
            route="fallback",
            confidence=0.0,
            signals=_signals(normalized, intent_id, "unknown"),
            reason="no stable business classification matched",
        )


def _result(
    *,
    question_type: BusinessQuestionType,
    route: BusinessRoute,
    confidence: float,
    target_tool: BusinessToolName | None = None,
    required_arguments: list[str] | None = None,
    missing_arguments: list[str] | None = None,
    extracted_arguments: dict[str, str] | None = None,
    requires_rag: bool = False,
    requires_confirmation: bool = False,
    risk_level: RiskLevel = "low",
    signals: list[str] | None = None,
    reason: str,
) -> BusinessQuestionClassification:
    return BusinessQuestionClassification(
        question_type=question_type,
        route=route,
        confidence=confidence,
        target_tool=target_tool,
        required_arguments=required_arguments or [],
        missing_arguments=missing_arguments or [],
        extracted_arguments=extracted_arguments or {},
        requires_rag=requires_rag,
        requires_confirmation=requires_confirmation,
        risk_level=risk_level,
        signals=signals or [],
        reason=reason,
    )


def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().casefold()


def _intent_id(intent_result: Any | None) -> str:
    value = getattr(intent_result, "intent_id", None)
    if value is None and isinstance(intent_result, dict):
        value = intent_result.get("intent_id")
    return str(value or "").strip()


def _intent_type(intent_result: Any | None) -> str:
    value = getattr(intent_result, "intent_type", None)
    if value is None and isinstance(intent_result, dict):
        value = intent_result.get("intent_type")
    return str(value or "").strip()


def _extract_order_id(text: str, tracker: Any | None) -> str | None:
    slot_value = _tracker_slot(tracker, "order_id")
    if slot_value is not None and _looks_like_order_id(str(slot_value)):
        return str(slot_value).strip()

    for pattern in EXPLICIT_ORDER_PATTERNS:
        match = pattern.search(text)
        if match and _looks_like_order_id(match.group("order_id")):
            return match.group("order_id").strip()

    if not _contains_any(text, ORDER_CONTEXT_KEYWORDS):
        return None

    for match in FALLBACK_ORDER_ID_RE.finditer(text):
        value = match.group("order_id").strip()
        if _looks_like_order_id(value) and not _looks_like_product_model(text, value):
            return value
    return None


def _tracker_slot(tracker: Any | None, key: str) -> Any | None:
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
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", text, flags=re.IGNORECASE):
        return False
    return any(ch.isdigit() for ch in text)


def _looks_like_product_model(text: str, value: str) -> bool:
    index = text.find(value)
    if index < 0:
        return False
    window = text[max(0, index - 8) : index + len(value) + 8]
    return _contains_any(window, PRODUCT_MODEL_MARKERS)


def _extract_invoice_title(text: str) -> str | None:
    for pattern in INVOICE_TITLE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        raw_title = match.group("title")
        title = _clean_invoice_title(raw_title)
        if title:
            return title
    return None


def _extract_ticket_no(text: str) -> str | None:
    match = TICKET_NO_RE.search(text)
    return match.group("ticket_no").upper() if match else None


def _clean_invoice_title(value: str) -> str | None:
    title = re.split(r"[,，。；;\s]", value.strip(), maxsplit=1)[0].strip("：:,.，。；;")
    if not title:
        return None
    if title in {"开发票", "发票", "开票"}:
        return None
    return title[:80]


def _missing_arguments(args: dict[str, str | None], required: tuple[str, ...]) -> list[str]:
    return [name for name in required if not args.get(name)]


def _compact_args(**kwargs: str | None) -> dict[str, str]:
    return {key: value for key, value in kwargs.items() if value}


def _is_complaint(text: str, intent_id: str) -> bool:
    return intent_id.startswith("F3_") or _contains_any(text, COMPLAINT_KEYWORDS)


def _is_ticket_status_query(text: str) -> bool:
    return _contains_any(text, TICKET_STATUS_QUERY_KEYWORDS)


def _is_invoice(text: str, intent_id: str) -> bool:
    return intent_id.startswith("S17_") or _contains_any(text, INVOICE_KEYWORDS)


def _is_invoice_policy(text: str, order_id: str | None) -> bool:
    if order_id:
        return False
    return _contains_any(text, POLICY_QUESTION_KEYWORDS) or _contains_any(text, INVOICE_POLICY_KEYWORDS)


def _is_logistics_query(text: str, intent_id: str) -> bool:
    return intent_id.startswith("S16_") or _contains_any(text, LOGISTICS_KEYWORDS)


def _is_order_query(text: str, intent_id: str) -> bool:
    if intent_id.startswith("S16_") or intent_id.startswith("S17_"):
        return False
    return _contains_any(text, ORDER_QUERY_KEYWORDS)


def _is_personal_order_request(text: str) -> bool:
    if _contains_any(text, POLICY_QUESTION_KEYWORDS) and not _contains_any(text, PERSONAL_QUERY_KEYWORDS):
        return False
    return _contains_any(text, PERSONAL_QUERY_KEYWORDS) or _contains_any(text, ORDER_CONTEXT_KEYWORDS)


def _is_policy_question(text: str, intent_type: str) -> bool:
    return intent_type in {"KB", "KB_TOOL", "KB_TICKET"} or _contains_any(text, GENERAL_POLICY_KEYWORDS)


def _signals(text: str, intent_id: str, primary: str) -> list[str]:
    signals = [primary]
    if intent_id:
        signals.append(f"intent:{intent_id}")
    for name, keywords in (
        ("complaint_keyword", COMPLAINT_KEYWORDS),
        ("invoice_keyword", INVOICE_KEYWORDS),
        ("logistics_keyword", LOGISTICS_KEYWORDS),
        ("order_keyword", ORDER_QUERY_KEYWORDS),
        ("policy_keyword", GENERAL_POLICY_KEYWORDS),
    ):
        if _contains_any(text, keywords):
            signals.append(name)
    return signals


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


EXPLICIT_ORDER_PATTERNS = (
    re.compile(r"(?:订单号?|单号|订单编号|order(?:\s*id)?)[\s:#：-]*(?P<order_id>[a-z0-9][a-z0-9_-]{3,63})", re.I),
)
FALLBACK_ORDER_ID_RE = re.compile(r"(?<![a-z0-9_-])(?P<order_id>[a-z]?\d[a-z0-9_-]{3,63})(?![a-z0-9_-])", re.I)
TICKET_NO_RE = re.compile(
    r"(?<![a-z0-9-])(?P<ticket_no>TKT-\d{8}-[A-F0-9]{12})(?![a-z0-9-])",
    re.I,
)

INVOICE_TITLE_PATTERNS = (
    re.compile(r"(?:发票抬头|抬头|公司名称|开票名称)[\s:：]*(?:是|为|写成)?[\s:：]*(?P<title>[\u4e00-\u9fa5a-z0-9（）()·.\-&]{2,80})", re.I),
    re.compile(r"开(?P<title>公司|个人|单位|企业)发票"),
    re.compile(r"(?P<title>公司|个人|单位|企业)发票"),
)

ORDER_CONTEXT_KEYWORDS = ("订单", "单号", "order", "购买记录", "物流", "快递", "发票", "开票", "到哪")
ORDER_QUERY_KEYWORDS = (
    "订单",
    "订单状态",
    "订单详情",
    "查订单",
    "查询订单",
    "支付状态",
    "买了什么",
    "购买记录",
)
LOGISTICS_KEYWORDS = (
    "物流",
    "快递",
    "配送",
    "发货",
    "到哪",
    "到哪了",
    "送到",
    "签收",
    "包裹",
    "运单",
    "运输",
)
INVOICE_KEYWORDS = ("发票", "开票", "抬头", "税号")
INVOICE_POLICY_KEYWORDS = ("怎么开发票", "如何开发票", "哪里开发票", "发票流程", "开票流程", "发票规则")
COMPLAINT_KEYWORDS = ("投诉", "客服态度", "态度差", "不满意", "差评", "消协", "欺骗", "举报")
TICKET_STATUS_QUERY_KEYWORDS = (
    "工单状态",
    "工单进度",
    "处理进度",
    "处理到哪",
    "ticket status",
    "ticket progress",
)
POLICY_QUESTION_KEYWORDS = ("怎么", "如何", "能不能", "可以吗", "规则", "流程", "政策", "条件")
GENERAL_POLICY_KEYWORDS = (
    "政策",
    "规则",
    "保修",
    "售后",
    "退货",
    "退款",
    "换货",
    "怎么",
    "如何",
    "能不能",
    "可以吗",
)
PERSONAL_QUERY_KEYWORDS = ("我的", "我这个", "帮我", "查一下", "查询", "看一下", "到哪了", "到哪里了")
PRODUCT_MODEL_MARKERS = ("小米", "redmi", "pro", "max", "ultra", "手机", "平板", "手表")
