from __future__ import annotations

import pytest

from app.intent import IntentCandidate, IntentResult, IntentRoutePolicy


def _intent(intent_id: str, intent_name: str, intent_type: str) -> IntentResult:
    return IntentResult(
        intent_id=intent_id,
        intent_name=intent_name,
        intent_type=intent_type,  # type: ignore[arg-type]
        confidence=0.91,
        candidates=[IntentCandidate(intent_id=intent_id, confidence=0.91)],
        source="llm_classifier",
    )


@pytest.mark.parametrize(
    ("case_id", "message", "intent_id", "intent_name", "intent_type", "route", "system_route", "requires_rag"),
    [
        ("F1-01", "我的扫地机充不进电了", "F1_故障报告", "故障报告", "KB_TICKET", "rag", "kb_ticket", True),
        ("F2-01", "希望 APP 能加个深色模式", "F2_功能建议", "功能建议", "TICKET", "ticket", "ticket", False),
        ("F2-02", "扫地机能不能加个语音播报关闭功能", "F2_功能建议", "功能建议", "TICKET", "ticket", "ticket", False),
        ("F3-01", "客服态度太差了", "F3_投诉吐槽", "投诉吐槽", "TICKET", "ticket", "ticket", False),
        ("S16-05", "我能改收货地址吗？已经发货了", "S16_物流配送", "物流配送", "KB_TOOL", "rag", "kb_tool", True),
        ("S14-01", "小米 14 Pro 保修期多久？", "S14_售后政策", "售后政策", "KB", "rag", "kb", True),
        ("S6-01", "小米 14 Pro 用什么充电器？", "S6_配件兼容", "配件兼容", "KB", "rag", "kb", True),
        ("C2-02", "苹果 15 Pro 怎么样？", "C2_越界提问", "越界提问", "CHITCHAT", "chitchat", "out_of_scope", False),
    ],
)
def test_route_policy_acceptance_cases(
    case_id: str,
    message: str,
    intent_id: str,
    intent_name: str,
    intent_type: str,
    route: str,
    system_route: str,
    requires_rag: bool,
) -> None:
    decision = IntentRoutePolicy().decide(_intent(intent_id, intent_name, intent_type), message)

    assert case_id
    assert decision.execution_route == route
    assert decision.system_route == system_route
    assert decision.requires_rag is requires_rag


def test_route_policy_f1_and_s16_do_not_enter_flow() -> None:
    policy = IntentRoutePolicy()

    f1 = policy.decide(_intent("F1_故障报告", "故障报告", "KB_TICKET"), "我的扫地机充不进电了")
    s16 = policy.decide(_intent("S16_物流配送", "物流配送", "KB_TOOL"), "我能改收货地址吗？已经发货了")

    assert f1.execution_route == "rag"
    assert s16.execution_route == "rag"
    assert "订单号" in f1.reason
    assert "订单号流程" in s16.reason
