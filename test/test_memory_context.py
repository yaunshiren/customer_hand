from __future__ import annotations

from app.agent.graph.nodes import generate_response, load_context
from app.core.tracker import DialogueStateTracker
from app.core.tracker_store import InMemoryTrackerStore
from app.memory import ConversationMemory, MemoryEntityExtractor, ProductCatalog, QueryRewriter
from app.settings import settings


def test_conversation_memory_default_contract() -> None:
    memory = ConversationMemory()

    assert memory.to_dict() == {
        "recent_turns": [],
        "memory_entities": {
            "product": "",
            "order_id": "",
            "intent": "",
        },
        "summary": "",
    }


def test_tracker_memory_keeps_recent_n_turns() -> None:
    tracker = DialogueStateTracker("memory_user", memory_turn_limit=2)

    tracker.update_with_user_message("turn 1 user")
    tracker.add_bot_message("turn 1 assistant")
    tracker.update_with_user_message("turn 2 user")
    tracker.add_bot_message("turn 2 assistant")
    tracker.update_with_user_message("turn 3 user")
    tracker.add_bot_message("turn 3 assistant")

    snapshot = tracker.memory.to_dict()
    assert [turn["user"] for turn in snapshot["recent_turns"]] == ["turn 2 user", "turn 3 user"]
    assert [turn["assistant"] for turn in snapshot["recent_turns"]] == ["turn 2 assistant", "turn 3 assistant"]
    assert snapshot["summary"] == ""


def test_tracker_memory_entities_use_defined_shape() -> None:
    tracker = DialogueStateTracker("memory_entity_user")

    tracker.set_slot("order_id", "A10001")
    tracker.memory.update_entities({"product": "XPhone Pro", "intent": "warranty"})

    assert tracker.memory.to_dict()["memory_entities"] == {
        "product": "XPhone Pro",
        "order_id": "A10001",
        "intent": "warranty",
    }


def test_tracker_from_dict_restores_memory_from_legacy_events() -> None:
    tracker = DialogueStateTracker.from_dict(
        {
            "sender_id": "legacy_memory_user",
            "events": [
                {"event": "user", "text": "legacy user", "timestamp": "2026-06-08T00:00:00Z"},
                {"event": "bot", "text": "legacy assistant", "timestamp": "2026-06-08T00:00:01Z"},
                {"event": "slot", "key": "order_id", "value": "B20002", "timestamp": "2026-06-08T00:00:02Z"},
            ],
        }
    )

    snapshot = tracker.memory.to_dict()
    assert snapshot["recent_turns"][0]["user"] == "legacy user"
    assert snapshot["recent_turns"][0]["assistant"] == "legacy assistant"
    assert snapshot["memory_entities"]["order_id"] == "B20002"


def test_store_tracker_preserves_memory_after_serialized_restore() -> None:
    store = InMemoryTrackerStore(memory_turn_limit=2)
    tracker = store.get_or_create("serialized_memory_user")
    tracker.update_with_user_message("hello")
    tracker.add_bot_message("hi")
    store.save(tracker)

    store._data["serialized_memory_user"] = tracker.to_dict()
    restored = store.retrieve("serialized_memory_user")

    assert restored is not None
    assert restored.memory.to_dict()["recent_turns"][0]["assistant"] == "hi"


def test_entity_extractor_finds_product_and_issue_type_from_user_text() -> None:
    extractor = MemoryEntityExtractor(ProductCatalog(["小米 14 Pro", "Redmi K70"]))

    result = extractor.extract(user_text="小米14 Pro 保修多久？")

    assert result.entities == {
        "product": "小米 14 Pro",
        "intent": "保修",
    }
    assert result.evidence["product"].source == "user"
    assert result.evidence["intent"].signal == "保修"


def test_entity_extractor_loads_product_catalog_from_knowledge_dir() -> None:
    extractor = MemoryEntityExtractor.from_knowledge_dir(settings.knowledge_dir)

    result = extractor.extract(user_text="小米14 Pro 保修多久？")

    assert result.entities["product"] == "小米 14 Pro"


def test_entity_extractor_finds_order_id_from_user_text() -> None:
    extractor = MemoryEntityExtractor(ProductCatalog(["小米 14 Pro"]))

    result = extractor.extract(user_text="帮我查一下订单 10001 到哪了")

    assert result.entities["order_id"] == "10001"
    assert result.entities["intent"] == "物流"


def test_memory_entity_updates_override_and_inherit_missing_entities() -> None:
    tracker = DialogueStateTracker("entity_memory_user")
    extractor = MemoryEntityExtractor(ProductCatalog(["小米 14 Pro"]))

    extractor.update_memory(tracker.memory, user_text="小米 14 Pro 保修多久？", tracker=tracker)
    assert tracker.memory.to_dict()["memory_entities"] == {
        "product": "小米 14 Pro",
        "order_id": "",
        "intent": "保修",
    }

    extractor.update_memory(tracker.memory, user_text="那换货呢？", tracker=tracker)
    assert tracker.memory.to_dict()["memory_entities"] == {
        "product": "小米 14 Pro",
        "order_id": "",
        "intent": "换货",
    }


def test_entity_extractor_can_update_from_assistant_text() -> None:
    tracker = DialogueStateTracker("assistant_entity_user")
    extractor = MemoryEntityExtractor(ProductCatalog(["小米 14 Pro"]))

    result = extractor.update_memory(
        tracker.memory,
        user_text="它支持七天无理由吗？",
        assistant_text="小米 14 Pro 未激活且包装完好时通常支持 7 天无理由退货。",
        tracker=tracker,
    )

    assert result.entities["product"] == "小米 14 Pro"
    assert tracker.memory.to_dict()["memory_entities"] == {
        "product": "小米 14 Pro",
        "order_id": "",
        "intent": "退货",
    }


def test_query_rewriter_resolves_product_pronoun_for_return_policy() -> None:
    memory = ConversationMemory()
    memory.update_entities({"product": "小米 14 Pro"})

    result = QueryRewriter().rewrite("那它可以 7 天无理由吗？", memory)

    assert result.original_query == "那它可以 7 天无理由吗？"
    assert result.rewritten_query == "小米 14 Pro 可以 7 天无理由退货吗？"
    assert result.memory_entities == {
        "product": "小米 14 Pro",
        "order_id": "",
        "intent": "",
    }
    assert result.rewrite_applied is True


def test_query_rewriter_keeps_self_contained_query_unchanged() -> None:
    memory = ConversationMemory()
    memory.update_entities({"product": "小米 14 Pro"})

    result = QueryRewriter().rewrite("小米 14 Pro 保修多久？", memory)

    assert result.rewritten_query == "小米 14 Pro 保修多久？"
    assert result.rewrite_applied is False
    assert result.reason == "query_already_self_contained"


def test_query_rewriter_resolves_order_followup() -> None:
    memory = ConversationMemory()
    memory.update_entities({"order_id": "A10001"})

    result = QueryRewriter().rewrite("它还能改地址吗？", memory)

    assert result.rewritten_query == "订单 A10001 还能改地址吗？"
    assert result.memory_entities["order_id"] == "A10001"


def test_query_rewriter_resolves_named_product_followup_marker() -> None:
    memory = ConversationMemory()
    memory.update_entities({"product": "小米 14 Pro"})

    result = QueryRewriter().rewrite("那款支持开发票吗？", memory)

    assert result.rewritten_query == "小米 14 Pro 支持开发票吗？"
    assert result.rewrite_applied is True


def test_query_rewriter_keeps_general_policy_query_unchanged() -> None:
    memory = ConversationMemory()
    memory.update_entities({"product": "小米 14 Pro"})

    result = QueryRewriter().rewrite("退货规则是什么？", memory)

    assert result.rewritten_query == "退货规则是什么？"
    assert result.rewrite_applied is False


def test_generate_response_exposes_memory_snapshot_metadata() -> None:
    state = load_context(
        {
            "sender_id": "memory_response_user",
            "message": "Where is order A10001?",
            "tracker": DialogueStateTracker("memory_response_user"),
            "memory_entity_extractor": MemoryEntityExtractor(ProductCatalog(["XPhone Pro"])),
        }
    )
    tracker = state["tracker"]
    tracker.set_slot("order_id", "A10001")

    result = generate_response(
        {
            **state,
            "route": "chitchat",
            "reply_text": "It is on the way.",
            "business_classification": {
                "question_type": "order_query",
                "extracted_arguments": {"order_id": "A10001"},
            },
        }
    )

    metadata = result["responses"][0]["metadata"]
    snapshot = metadata["memory_snapshot"]
    assert snapshot["recent_turns"][-1]["user"] == "Where is order A10001?"
    assert snapshot["recent_turns"][-1]["assistant"] == "It is on the way."
    assert metadata["memory_entities"] == {
        "product": "",
        "order_id": "A10001",
        "intent": "订单查询",
    }
    assert metadata["memory_extraction"]["entities"]["order_id"] == "A10001"


def test_generate_response_exposes_query_rewrite_metadata() -> None:
    tracker = DialogueStateTracker("rewrite_metadata_user")

    result = generate_response(
        {
            "sender_id": "rewrite_metadata_user",
            "message": "那它可以 7 天无理由吗？",
            "tracker": tracker,
            "route": "rag",
            "knowledge_answer": "可以。",
            "rag_query": "小米 14 Pro 可以 7 天无理由退货吗？",
            "query_rewrite": {
                "original_query": "那它可以 7 天无理由吗？",
                "rewritten_query": "小米 14 Pro 可以 7 天无理由退货吗？",
                "memory_entities": {"product": "小米 14 Pro", "order_id": "", "intent": ""},
                "rewrite_applied": True,
                "reason": "contextual_reference_resolved",
            },
            "rag_matches": [],
            "used_llm": False,
        }
    )

    metadata = result["responses"][0]["metadata"]
    assert metadata["original_query"] == "那它可以 7 天无理由吗？"
    assert metadata["rewritten_query"] == "小米 14 Pro 可以 7 天无理由退货吗？"
    assert metadata["query_rewrite"]["memory_entities"]["product"] == "小米 14 Pro"
