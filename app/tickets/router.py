from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HumanHandoffDecision:
    should_handoff: bool
    reason: str


_HANDOFF_KEYWORDS = (
    "人工",
    "转人工",
    "我要客服",
    "我要投诉",
    "客服",
    "没人处理",
)

_STUCK_KEYWORDS = (
    "缺订单号",
    "没订单号",
    "缺手机号",
    "没手机号",
    "缺商品信息",
    "信息不全",
    "补充信息",
)

_REPEAT_KEYWORDS = (
    "重复",
    "还是不行",
    "没解决",
    "一直这样",
    "又来了",
)


def should_handoff_to_human(text: str, confidence: float | None = None, unresolved_turns: int = 0) -> HumanHandoffDecision:
    normalized_text = text.strip()

    if not normalized_text:
        return HumanHandoffDecision(should_handoff=True, reason="用户未提供有效问题描述")

    if any(keyword in normalized_text for keyword in _HANDOFF_KEYWORDS):
        return HumanHandoffDecision(should_handoff=True, reason="用户明确要求人工处理")

    if confidence is not None and confidence < 0.55:
        return HumanHandoffDecision(should_handoff=True, reason="知识库置信度过低")

    if unresolved_turns >= 2:
        return HumanHandoffDecision(should_handoff=True, reason="连续多轮未解决")

    if any(keyword in normalized_text for keyword in _STUCK_KEYWORDS):
        return HumanHandoffDecision(should_handoff=True, reason="关键信息缺失导致流程卡住")

    if any(keyword in normalized_text for keyword in _REPEAT_KEYWORDS):
        return HumanHandoffDecision(should_handoff=True, reason="用户反馈问题仍未解决")

    return HumanHandoffDecision(should_handoff=False, reason="当前可继续自动处理")
