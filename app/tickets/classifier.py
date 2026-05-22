from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryRule:
    category: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class PriorityRule:
    priority: str
    keywords: tuple[str, ...]


_CATEGORY_RULES: tuple[CategoryRule, ...] = (
    CategoryRule(category="refund", keywords=("退货", "退款", "退钱")),
    CategoryRule(category="logistics", keywords=("物流", "快递", "到哪", "运输")),
    CategoryRule(category="complaint", keywords=("人工", "客服", "投诉")),
    CategoryRule(category="knowledge_miss", keywords=("查不到", "没找到", "知识库", "规则")),
    CategoryRule(category="pre_sale", keywords=("下单", "购买", "咨询", "推荐")),
    CategoryRule(category="order", keywords=("订单", "支付", "发货", "取消订单")),
    CategoryRule(category="other", keywords=()),
)

_PRIORITY_RULES: tuple[PriorityRule, ...] = (
    PriorityRule(priority="urgent", keywords=("投诉", "退款失败", "一直没人处理")),
    PriorityRule(priority="high", keywords=("商品损坏", "发错货", "错发")),
    PriorityRule(priority="medium", keywords=("麻烦", "尽快", "请问", "咨询")),
    PriorityRule(priority="low", keywords=()),
)


def classify_ticket_category(text: str) -> str:
    normalized_text = text.strip()
    if not normalized_text:
        return "other"

    for rule in _CATEGORY_RULES:
        if rule.category == "other":
            continue
        if any(keyword in normalized_text for keyword in rule.keywords):
            return rule.category

    return "other"


def classify_ticket_priority(text: str) -> str:
    normalized_text = text.strip()
    if not normalized_text:
        return "low"

    for rule in _PRIORITY_RULES:
        if rule.priority == "low":
            continue
        if any(keyword in normalized_text for keyword in rule.keywords):
            return rule.priority

    return "low"
