from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class QueryRewriteResult:
    original_query: str
    rewritten_query: str
    memory_entities: dict[str, str] = field(default_factory=dict)
    rewrite_applied: bool = False
    reason: str = "unchanged"

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_query": self.original_query,
            "rewritten_query": self.rewritten_query,
            "memory_entities": dict(self.memory_entities),
            "rewrite_applied": self.rewrite_applied,
            "reason": self.reason,
        }


class QueryRewriter:
    def rewrite(self, query: str, memory: Any | None = None) -> QueryRewriteResult:
        original_query = _clean_query(query)
        if not original_query:
            return QueryRewriteResult(original_query="", rewritten_query="", memory_entities={})

        memory_data = _memory_to_dict(memory)
        entities = _memory_entities(memory_data)
        if _contains_known_entity(original_query, entities):
            return QueryRewriteResult(
                original_query=original_query,
                rewritten_query=original_query,
                memory_entities=entities,
                rewrite_applied=False,
                reason="query_already_self_contained",
            )

        target = _select_target_entity(original_query, entities)
        if not target:
            return QueryRewriteResult(
                original_query=original_query,
                rewritten_query=original_query,
                memory_entities=entities,
                rewrite_applied=False,
                reason="no_memory_entity",
            )

        if not _needs_rewrite(original_query):
            return QueryRewriteResult(
                original_query=original_query,
                rewritten_query=original_query,
                memory_entities=entities,
                rewrite_applied=False,
                reason="no_contextual_reference",
            )

        rewritten = _join_entity_and_question(target, original_query)
        return QueryRewriteResult(
            original_query=original_query,
            rewritten_query=rewritten,
            memory_entities=entities,
            rewrite_applied=rewritten != original_query,
            reason="contextual_reference_resolved" if rewritten != original_query else "unchanged",
        )


def _memory_to_dict(memory: Any | None) -> dict[str, Any]:
    if memory is None:
        return {}
    if hasattr(memory, "to_dict"):
        data = memory.to_dict()
        return dict(data) if isinstance(data, dict) else {}
    if isinstance(memory, dict):
        return dict(memory)
    return {}


def _memory_entities(memory_data: dict[str, Any]) -> dict[str, str]:
    raw = memory_data.get("memory_entities")
    data = raw if isinstance(raw, dict) else {}
    return {
        "product": _clean_query(data.get("product")),
        "order_id": _clean_query(data.get("order_id")),
        "intent": _clean_query(data.get("intent")),
    }


def _contains_known_entity(query: str, entities: dict[str, str]) -> bool:
    query_compact = _compact(query)
    for key in ("product", "order_id"):
        value = entities.get(key) or ""
        if value and _compact(value) in query_compact:
            return True
    return False


def _select_target_entity(query: str, entities: dict[str, str]) -> str:
    product = entities.get("product") or ""
    order_id = entities.get("order_id") or ""
    if order_id and _is_order_followup(query):
        return f"订单 {order_id}"
    if product:
        return product
    if order_id:
        return f"订单 {order_id}"
    return ""


def _needs_rewrite(query: str) -> bool:
    normalized = _normalize(query)
    if not normalized:
        return False
    if any(marker in normalized for marker in CONTEXT_REFERENCE_MARKERS):
        return True
    if normalized.startswith(("那", "那么", "这个", "这款", "那款")):
        return True
    if _is_short_followup(normalized) and not _is_general_policy_query(normalized):
        return True
    return False


def _is_short_followup(normalized_query: str) -> bool:
    compact = _compact(normalized_query)
    if len(compact) > 28:
        return False
    return any(keyword in normalized_query for keyword in SHORT_FOLLOWUP_KEYWORDS)


def _is_general_policy_query(normalized_query: str) -> bool:
    if any(marker in normalized_query for marker in CONTEXT_REFERENCE_MARKERS):
        return False
    return any(keyword in normalized_query for keyword in GENERAL_POLICY_KEYWORDS)


def _is_order_followup(query: str) -> bool:
    normalized = _normalize(query)
    return any(keyword in normalized for keyword in ORDER_FOLLOWUP_KEYWORDS)


def _join_entity_and_question(entity: str, query: str) -> str:
    question = _clean_followup_question(query)
    if not question:
        return entity

    question = _normalize_issue_question(question)
    if not question:
        return entity

    if _compact(entity) in _compact(question):
        return question
    if _starts_with_question_verb(question):
        return f"{entity} {question}"
    return f"{entity} {question}"


def _clean_followup_question(query: str) -> str:
    text = _clean_query(query)
    text = re.sub(r"^(?:刚才那个|刚刚那个|上面那个|前面那个|那么|这个|这款|那款|那|请问)[，,\s]*", "", text)
    for pattern in PRONOUN_PATTERNS:
        text = pattern.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[，,。！？?\s]+", "", text)
    return text


def _normalize_issue_question(question: str) -> str:
    text = question.strip()
    if not text:
        return ""

    text = _normalize_return_question(text)
    text = _normalize_short_issue_question(text)
    return text


def _normalize_return_question(question: str) -> str:
    if not _contains_return_window(question):
        return question
    if any(term in question for term in ("退货", "退换", "退款")):
        return question

    suffix = _question_suffix(question)
    stem = _strip_question_suffix(question)
    had_modal_particle = bool(re.search(r"[吗嘛么]$", stem))
    stem = re.sub(r"[吗嘛么]$", "", stem).strip()
    if stem.endswith("无理由"):
        stem = f"{stem}退货"
    else:
        stem = f"{stem} 退货"
    return f"{stem}{'吗' if had_modal_particle else ''}{suffix}"


def _normalize_short_issue_question(question: str) -> str:
    body = _strip_question_suffix(question)
    compact = _compact(body)
    suffix = _question_suffix(question)
    for issue in SHORT_ISSUE_TERMS:
        if compact in {
            _compact(issue),
            _compact(f"{issue}呢"),
            _compact(f"{issue}吗"),
            _compact(f"{issue}嘛"),
            _compact(f"那{issue}呢"),
        }:
            return f"可以{issue}吗{_fullwidth_suffix(suffix)}"
    return question


def _question_suffix(question: str) -> str:
    return "？" if question.endswith("？") else "?" if question.endswith("?") else "？"


def _fullwidth_suffix(suffix: str) -> str:
    return "？" if suffix in {"？", "?"} else suffix


def _strip_question_suffix(question: str) -> str:
    return question.rstrip("？?").strip()


def _contains_return_window(text: str) -> bool:
    normalized = _normalize(text)
    return any(term in normalized for term in RETURN_WINDOW_TERMS)


def _starts_with_question_verb(question: str) -> bool:
    normalized = _normalize(question)
    return normalized.startswith(("可以", "能", "能不能", "支持", "还能", "是否", "可不可以"))


def _clean_query(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", _normalize(value))


CONTEXT_REFERENCE_MARKERS = (
    "它",
    "这个",
    "那个",
    "这款",
    "那款",
    "这台",
    "那台",
    "刚才那个",
    "刚刚那个",
    "上面那个",
    "前面那个",
)

PRONOUN_PATTERNS = (
    re.compile(r"(?:它|这个商品|这个产品|这个|那个商品|那个产品|那个|这款|那款|这台|那台)"),
)

SHORT_FOLLOWUP_KEYWORDS = (
    "保修",
    "退货",
    "退款",
    "换货",
    "7天无理由",
    "7 天无理由",
    "七天无理由",
    "开发票",
    "发票",
    "到哪",
    "物流",
    "改地址",
    "充电器",
    "可以",
    "支持",
    "能不能",
)

GENERAL_POLICY_KEYWORDS = (
    "规则是什么",
    "政策是什么",
    "流程是什么",
    "怎么申请",
    "怎么办理",
)

ORDER_FOLLOWUP_KEYWORDS = (
    "订单",
    "物流",
    "快递",
    "到哪",
    "发货",
    "配送",
    "改地址",
    "收货地址",
    "发票",
    "开票",
)

RETURN_WINDOW_TERMS = (
    "7天无理由",
    "7 天无理由",
    "七天无理由",
)

SHORT_ISSUE_TERMS = (
    "保修",
    "退货",
    "换货",
    "退款",
    "开发票",
    "发票",
)
