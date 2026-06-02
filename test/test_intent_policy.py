from __future__ import annotations

from app.core.tracker import DialogueStateTracker
from app.intent import IntentCandidate, IntentResult, IntentRoutePolicy


def _intent(
    intent_id: str,
    intent_name: str,
    intent_type: str,
    *,
    candidates: list[IntentCandidate] | None = None,
) -> IntentResult:
    return IntentResult(
        intent_id=intent_id,
        intent_name=intent_name,
        intent_type=intent_type,  # type: ignore[arg-type]
        confidence=0.9,
        candidates=candidates or [IntentCandidate(intent_id=intent_id, confidence=0.9)],
        source="llm_classifier",
    )


def test_s16_logistics_routes_to_rag_first_without_order_flow() -> None:
    decision = IntentRoutePolicy().decide(
        _intent("S16_物流配送", "物流配送", "KB_TOOL"),
        "我能改收货地址吗？已经发货了",
    )

    assert decision.execution_route == "rag"
    assert decision.system_route == "kb_tool"
    assert decision.requires_rag is True
    assert "订单号流程" in decision.reason


def test_s16_with_order_id_still_routes_to_rag_in_first_version() -> None:
    tracker = DialogueStateTracker("u1")
    tracker.set_slot("order_id", "A12345678")

    decision = IntentRoutePolicy().decide(
        _intent("S16_物流配送", "物流配送", "KB_TOOL"),
        "帮我查一下物流",
        tracker,
    )

    assert decision.execution_route == "rag"
    assert decision.system_route == "kb_tool"
    assert "第一版仍先走 RAG" in decision.reason


def test_f1_fault_report_routes_to_rag_not_order_flow() -> None:
    decision = IntentRoutePolicy().decide(
        _intent("F1_故障报告", "故障报告", "KB_TICKET"),
        "我的扫地机充不进电了",
    )

    assert decision.execution_route == "rag"
    assert decision.system_route == "kb_ticket"
    assert decision.requires_rag is True
    assert "不直接索要订单号" in decision.reason


def test_f2_feature_suggestion_does_not_use_rag() -> None:
    decision = IntentRoutePolicy().decide(
        _intent("F2_功能建议", "功能建议", "TICKET"),
        "希望 APP 能加个深色模式",
    )

    assert decision.execution_route == "ticket"
    assert decision.system_route == "ticket"
    assert decision.requires_rag is False


def test_simple_f3_complaint_routes_to_ticket_without_rag() -> None:
    decision = IntentRoutePolicy().decide(
        _intent("F3_投诉吐槽", "投诉吐槽", "TICKET"),
        "客服态度太差了",
    )

    assert decision.execution_route == "ticket"
    assert decision.system_route == "ticket"
    assert decision.requires_rag is False


def test_f3_complaint_with_logistics_fact_can_use_rag_first() -> None:
    decision = IntentRoutePolicy().decide(
        _intent(
            "F3_投诉吐槽",
            "投诉吐槽",
            "TICKET",
            candidates=[
                IntentCandidate(intent_id="F3_投诉吐槽", confidence=0.95),
                IntentCandidate(intent_id="S16_物流配送", confidence=0.72),
            ],
        ),
        "我要投诉，快递一周还没发货",
    )

    assert decision.execution_route == "rag"
    assert decision.system_route == "kb_ticket"
    assert decision.requires_rag is True


def test_c2_out_of_scope_does_not_use_rag() -> None:
    decision = IntentRoutePolicy().decide(
        _intent("C2_越界提问", "越界提问", "CHITCHAT"),
        "苹果 15 Pro 怎么样",
    )

    assert decision.execution_route == "chitchat"
    assert decision.system_route == "out_of_scope"
    assert decision.requires_rag is False


def test_kb_intent_routes_to_rag() -> None:
    decision = IntentRoutePolicy().decide(
        _intent("S14_售后政策", "售后政策", "KB"),
        "小米 14 Pro 保修期多久？",
    )

    assert decision.execution_route == "rag"
    assert decision.system_route == "kb"
    assert decision.requires_rag is True


def test_unknown_intent_routes_to_fallback_without_rag() -> None:
    decision = IntentRoutePolicy().decide(
        _intent("UNKNOWN", "未知", "UNKNOWN", candidates=[]),
        "随便说点什么",
    )

    assert decision.execution_route == "fallback"
    assert decision.system_route == "unknown"
    assert decision.requires_rag is False
