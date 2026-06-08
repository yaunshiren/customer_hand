from __future__ import annotations

from app.agent.graph.nodes import load_context, rag, route, understand
from app.core.tracker import DialogueStateTracker
from app.intent import IntentCandidate, IntentResult
from app.memory import MemoryEntityExtractor, ProductCatalog
from app.rag.answerer import KnowledgeAnswerer


def _intent(intent_id: str, intent_name: str, intent_type: str) -> IntentResult:
    return IntentResult(
        intent_id=intent_id,
        intent_name=intent_name,
        intent_type=intent_type,  # type: ignore[arg-type]
        confidence=0.91,
        candidates=[IntentCandidate(intent_id=intent_id, confidence=0.91)],
        reason="测试分类结果",
        source="llm_classifier",
    )


class FakeClassifier:
    def __init__(self, result: IntentResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def classify(self, text: str) -> IntentResult:
        self.calls.append(text)
        return self.result


class ExplodingClassifier:
    def classify(self, text: str) -> IntentResult:
        raise AssertionError("route should not classify again")


class EmptyCommandGenerator:
    enabled = False

    def generate(self, tracker, text: str, flow_ids: list[str] | None = None) -> dict[str, object]:
        return {"handled": False, "reply_text": None, "results": [], "raw_output": ""}


class RecordingKnowledgeAnswerer(KnowledgeAnswerer):
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str | None]] = []

    def answer(self, query: str, top_k: int = 3, intent_id: str | None = None) -> dict[str, object]:
        self.calls.append((query, top_k, intent_id))
        return {"answer": "ok", "matches": [], "used_llm": False}


def _tracker_after_first_turn(
    *,
    sender_id: str,
    user_text: str,
    product_names: list[str] | None = None,
) -> DialogueStateTracker:
    tracker = DialogueStateTracker(sender_id)
    state = load_context(
        {
            "sender_id": sender_id,
            "message": user_text,
            "tracker": tracker,
            "memory_entity_extractor": MemoryEntityExtractor(ProductCatalog(product_names or [])),
        }
    )
    tracker = state["tracker"]
    tracker.add_bot_message("ok")
    return tracker


def _rag_after_second_turn(
    *,
    tracker: DialogueStateTracker,
    sender_id: str,
    user_text: str,
    answerer: RecordingKnowledgeAnswerer,
    product_names: list[str] | None = None,
) -> dict[str, object]:
    state = load_context(
        {
            "sender_id": sender_id,
            "message": user_text,
            "tracker": tracker,
            "memory_entity_extractor": MemoryEntityExtractor(ProductCatalog(product_names or [])),
        }
    )
    return rag(
        {
            **state,
            "llm_results": [],
            "knowledge_answerer": answerer,
            "intent_result": _intent("S14_售后政策", "售后政策", "KB"),
        }
    )


def test_understand_adds_intent_result_to_state() -> None:
    classifier = FakeClassifier(_intent("S16_物流配送", "物流配送", "KB_TOOL"))
    tracker = DialogueStateTracker("intent_understand_user")

    state = understand(
        {
            "sender_id": "intent_understand_user",
            "message": "我能改收货地址吗？已经发货了",
            "tracker": tracker,
            "flows": {},
            "llm_generator": EmptyCommandGenerator(),
            "intent_classifier": classifier,
        }
    )

    assert state["intent_result"].intent_id == "S16_物流配送"
    assert classifier.calls == ["我能改收货地址吗？已经发货了"]


def test_route_uses_existing_intent_result_without_reclassifying() -> None:
    tracker = DialogueStateTracker("intent_route_user")

    state = route(
        {
            "sender_id": "intent_route_user",
            "message": "希望 APP 能加个深色模式",
            "tracker": tracker,
            "llm_result": {"handled": False},
            "llm_results": [],
            "reply_text": None,
            "llm_generator": EmptyCommandGenerator(),
            "intent_classifier": ExplodingClassifier(),
            "intent_result": _intent("F2_功能建议", "功能建议", "TICKET"),
        }
    )

    assert state["route"] == "ticket"
    assert state["route_decision"]["system_route"] == "ticket"


def test_route_falls_back_to_legacy_logic_when_intent_missing() -> None:
    tracker = DialogueStateTracker("intent_missing_user")

    state = route(
        {
            "sender_id": "intent_missing_user",
            "message": "查物流",
            "tracker": tracker,
            "llm_result": {"handled": False},
            "llm_results": [],
            "reply_text": None,
            "llm_generator": EmptyCommandGenerator(),
            "intent_classifier": ExplodingClassifier(),
        }
    )

    assert state["route"] == "flow"


def test_route_propagates_policy_metadata_fields() -> None:
    tracker = DialogueStateTracker("intent_metadata_user")

    state = route(
        {
            "sender_id": "intent_metadata_user",
            "message": "我的扫地机充不进电了",
            "tracker": tracker,
            "llm_result": {"handled": False},
            "llm_results": [],
            "reply_text": None,
            "llm_generator": EmptyCommandGenerator(),
            "intent_result": _intent("F1_故障报告", "故障报告", "KB_TICKET"),
        }
    )

    assert state["route"] == "rag"
    assert state["intent_result"]["intent_id"] == "F1_故障报告"
    assert state["route_decision"]["system_route"] == "kb_ticket"


def test_rag_passes_intent_id_to_knowledge_answerer() -> None:
    answerer = RecordingKnowledgeAnswerer()

    state = rag(
        {
            "message": "小米 14 Pro 保修期多久？",
            "llm_results": [],
            "knowledge_answerer": answerer,
            "intent_result": _intent("S14_售后政策", "售后政策", "KB"),
        }
    )

    assert answerer.calls == [("小米 14 Pro 保修期多久？", 3, "S14_售后政策")]
    assert state["knowledge_answer"] == "ok"


def test_rag_uses_rewritten_query_from_memory() -> None:
    answerer = RecordingKnowledgeAnswerer()
    tracker = DialogueStateTracker("rewrite_rag_user")
    tracker.memory.update_entities({"product": "小米 14 Pro"})

    state = rag(
        {
            "message": "那它可以 7 天无理由吗？",
            "tracker": tracker,
            "llm_results": [],
            "knowledge_answerer": answerer,
            "intent_result": _intent("S14_售后政策", "售后政策", "KB"),
        }
    )

    assert answerer.calls == [("小米 14 Pro 可以 7 天无理由退货吗？", 3, "S14_售后政策")]
    assert state["rag_query"] == "小米 14 Pro 可以 7 天无理由退货吗？"
    assert state["query_rewrite"]["original_query"] == "那它可以 7 天无理由吗？"
    assert state["query_rewrite"]["rewritten_query"] == "小米 14 Pro 可以 7 天无理由退货吗？"
    assert state["query_rewrite"]["memory_entities"]["product"] == "小米 14 Pro"


def test_multiturn_acceptance_product_pronoun_rewrite_uses_rewritten_query() -> None:
    answerer = RecordingKnowledgeAnswerer()
    tracker = _tracker_after_first_turn(
        sender_id="accept_product_rewrite_user",
        user_text="小米 14 Pro 保修多久？",
        product_names=["小米 14 Pro"],
    )

    state = _rag_after_second_turn(
        tracker=tracker,
        sender_id="accept_product_rewrite_user",
        user_text="那它可以 7 天无理由吗？",
        answerer=answerer,
        product_names=["小米 14 Pro"],
    )

    assert answerer.calls == [("小米 14 Pro 可以 7 天无理由退货吗？", 3, "S14_售后政策")]
    assert state["query_rewrite"] == {
        "original_query": "那它可以 7 天无理由吗？",
        "rewritten_query": "小米 14 Pro 可以 7 天无理由退货吗？",
        "memory_entities": {
            "product": "小米 14 Pro",
            "order_id": "",
            "intent": "退货",
        },
        "rewrite_applied": True,
        "reason": "contextual_reference_resolved",
    }


def test_multiturn_acceptance_order_pronoun_rewrite_uses_rewritten_query() -> None:
    answerer = RecordingKnowledgeAnswerer()
    tracker = _tracker_after_first_turn(
        sender_id="accept_order_rewrite_user",
        user_text="订单 123456 到哪了？",
    )

    state = _rag_after_second_turn(
        tracker=tracker,
        sender_id="accept_order_rewrite_user",
        user_text="它还能改地址吗？",
        answerer=answerer,
    )

    assert answerer.calls == [("订单 123456 还能改地址吗？", 3, "S14_售后政策")]
    assert state["query_rewrite"]["original_query"] == "它还能改地址吗？"
    assert state["query_rewrite"]["rewritten_query"] == "订单 123456 还能改地址吗？"
    assert state["query_rewrite"]["memory_entities"]["order_id"] == "123456"
    assert state["query_rewrite"]["rewrite_applied"] is True


def test_multiturn_acceptance_issue_type_followup_rewrite_uses_rewritten_query() -> None:
    answerer = RecordingKnowledgeAnswerer()
    tracker = _tracker_after_first_turn(
        sender_id="accept_issue_followup_user",
        user_text="华为 Mate 60 支持退货吗？",
        product_names=["华为 Mate 60"],
    )

    state = _rag_after_second_turn(
        tracker=tracker,
        sender_id="accept_issue_followup_user",
        user_text="那换货呢？",
        answerer=answerer,
        product_names=["华为 Mate 60"],
    )

    assert answerer.calls == [("华为 Mate 60 可以换货吗？", 3, "S14_售后政策")]
    assert state["query_rewrite"]["original_query"] == "那换货呢？"
    assert state["query_rewrite"]["rewritten_query"] == "华为 Mate 60 可以换货吗？"
    assert state["query_rewrite"]["memory_entities"]["product"] == "华为 Mate 60"
    assert state["query_rewrite"]["memory_entities"]["intent"] == "换货"
    assert state["query_rewrite"]["rewrite_applied"] is True


def test_route_does_not_enter_flow_when_policy_overrides_start_flow() -> None:
    tracker = DialogueStateTracker("intent_start_flow_user")
    tracker.active_flow = "logistics"

    state = route(
        {
            "sender_id": "intent_start_flow_user",
            "message": "我能改收货地址吗？已经发货了",
            "tracker": tracker,
            "llm_result": {"handled": True},
            "llm_results": [{"type": "start_flow", "success": True, "data": {"flow_id": "logistics"}}],
            "reply_text": None,
            "llm_generator": EmptyCommandGenerator(),
            "intent_result": _intent("S16_物流配送", "物流配送", "KB_TOOL"),
        }
    )

    assert state["route"] == "rag"
    assert tracker.active_flow is None
    assert tracker.slot_to_collect is None


def test_route_keeps_set_slot_compatibility_for_active_flow() -> None:
    tracker = DialogueStateTracker("intent_slot_user")
    tracker.active_flow = "logistics"

    state = route(
        {
            "sender_id": "intent_slot_user",
            "message": "A12345678",
            "tracker": tracker,
            "llm_result": {"handled": True},
            "llm_results": [{"type": "set_slot", "success": True, "data": {"name": "order_id", "value": "A12345678"}}],
            "reply_text": None,
            "llm_generator": EmptyCommandGenerator(),
            "intent_result": _intent("S16_物流配送", "物流配送", "KB_TOOL"),
        }
    )

    assert state["route"] == "flow"
