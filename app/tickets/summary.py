from __future__ import annotations

from dataclasses import dataclass

from .classifier import classify_ticket_category, classify_ticket_priority


@dataclass(frozen=True)
class SummaryResult:
    title: str
    summary: str
    category: str
    priority: str
    suggestion: str


def build_ticket_summary(text: str) -> SummaryResult:
    normalized_text = text.strip()
    category = classify_ticket_category(normalized_text)
    priority = classify_ticket_priority(normalized_text)

    if not normalized_text:
        return SummaryResult(
            title="用户未提供有效工单内容",
            summary="用户输入为空或无法识别，当前无法生成具体摘要。",
            category="other",
            priority="low",
            suggestion="建议先补充用户的问题描述，再继续处理。",
        )

    if category == "refund":
        return SummaryResult(
            title="用户申请退货或退款",
            summary="用户表达了退货、退款或退钱相关诉求。",
            category=category,
            priority=priority,
            suggestion="建议客服核对订单号、签收时间和商品状态；若符合退货规则，可引导用户提交售后申请。",
        )

    if category == "logistics":
        return SummaryResult(
            title="用户咨询物流进度",
            summary="用户关注快递、运输或物流到达情况。",
            category=category,
            priority=priority,
            suggestion="建议客服查询物流单号、当前运输节点和预计送达时间，并同步给用户。",
        )

    if category == "complaint":
        return SummaryResult(
            title="用户提出投诉或人工客服诉求",
            summary="用户希望转人工处理或对服务过程提出投诉。",
            category=category,
            priority=priority,
            suggestion="建议优先安抚用户情绪，确认问题细节，并尽快转交人工客服跟进。",
        )

    if category == "knowledge_miss":
        return SummaryResult(
            title="知识库未命中用户问题",
            summary="系统未能在知识库中找到与用户问题匹配的答案。",
            category=category,
            priority=priority,
            suggestion="建议补充知识库内容，或由客服人工确认后再回复用户。",
        )

    if category == "pre_sale":
        return SummaryResult(
            title="用户咨询售前问题",
            summary="用户正在了解商品、下单或购买相关信息。",
            category=category,
            priority=priority,
            suggestion="建议客服说明商品信息、活动规则和下单流程，帮助用户完成购买。",
        )

    if category == "order":
        return SummaryResult(
            title="用户咨询订单问题",
            summary="用户在订单、支付、发货或取消订单方面遇到问题。",
            category=category,
            priority=priority,
            suggestion="建议客服核对订单状态、支付状态和发货状态，再给出下一步处理建议。",
        )

    return SummaryResult(
        title="用户问题待进一步确认",
        summary="用户描述了一个未能明确归类的问题，需要进一步核实。",
        category=category,
        priority=priority,
        suggestion="建议客服先确认用户具体诉求，再根据实际情况处理。",
    )
