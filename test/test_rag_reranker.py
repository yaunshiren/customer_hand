from __future__ import annotations

from app.rag.documents import KnowledgeChunk
from app.rag.indexer import RetrievalMatch
from app.rag.reranker import RuleBasedReranker


def _match(
    *,
    doc_id: str,
    title: str,
    text: str,
    score: float,
    metadata: dict[str, object] | None = None,
) -> RetrievalMatch:
    chunk = KnowledgeChunk(
        chunk_id=f"{doc_id}-0",
        source=f"{doc_id}.md",
        text=text,
        metadata={"doc_id": doc_id, "title": title, **(metadata or {})},
    )
    return RetrievalMatch(chunk=chunk, score=score)


def test_reranker_promotes_warranty_policy_over_product_detail() -> None:
    candidates = [
        _match(
            doc_id="PROD_PHONE_004",
            title="小米 14 Pro 商品详情",
            text="小米 14 Pro 屏幕、处理器和影像参数说明。",
            score=0.95,
            metadata={
                "product_names": ["小米 14 Pro"],
                "intent_ids": ["S2_参数咨询", "S6_配件兼容"],
                "category": "product_detail",
            },
        ),
        _match(
            doc_id="POLICY_WAR_002",
            title="各品类保修期与保修范围",
            text="手机类商品保修期为一年，非人为性能故障可按售后政策免费维修。",
            score=0.55,
            metadata={
                "intent_ids": ["S14_售后政策"],
                "category": "policy_warranty",
                "keywords": ["保修期", "免费维修", "售后政策"],
            },
        ),
    ]

    result = RuleBasedReranker().rerank(
        "小米 14 Pro 保修期多久？",
        candidates,
        intent_id="S14_售后政策",
    )

    assert result[0].chunk.metadata["doc_id"] == "POLICY_WAR_002"
    signals = {item["name"] for item in result[0].chunk.metadata["rerank_signals"]}
    assert {"intent_match", "title_keyword_hit", "policy_term_hit"}.issubset(signals)


def test_reranker_promotes_charger_accessory_document() -> None:
    candidates = [
        _match(
            doc_id="PROD_PHONE_004",
            title="小米 14 Pro 商品详情",
            text="小米 14 Pro 屏幕、影像、重量和机身参数。",
            score=0.95,
            metadata={
                "product_names": ["小米 14 Pro"],
                "intent_ids": ["S2_参数咨询"],
                "category": "product_detail",
            },
        ),
        _match(
            doc_id="MANUAL_PHONE_001",
            title="小米手机充电器与配件兼容说明",
            text="小米 14 Pro 建议使用 120W 原装充电器，兼容标准 USB-C 充电线。",
            score=0.50,
            metadata={
                "product_names": ["小米 14 Pro"],
                "intent_ids": ["S6_配件兼容"],
                "category": "manual_product",
                "keywords": ["充电器", "充电线", "配件", "兼容"],
            },
        ),
    ]

    result = RuleBasedReranker().rerank(
        "小米 14 Pro 用什么充电器？",
        candidates,
        intent_id="S6_配件兼容",
    )

    assert result[0].chunk.metadata["doc_id"] == "MANUAL_PHONE_001"
    signals = {item["name"] for item in result[0].chunk.metadata["rerank_signals"]}
    assert {"intent_match", "product_exact_match", "domain_term_hit"}.issubset(signals)


def test_reranker_promotes_logistics_address_policy() -> None:
    candidates = [
        _match(
            doc_id="APP_GUIDE_001",
            title="比特APP 基础使用指南（订单/地址/收藏）",
            text="用户可以在 APP 中查看订单、管理地址和收藏商品。",
            score=0.90,
            metadata={
                "intent_ids": ["S10_APP功能"],
                "category": "manual_app",
                "keywords": ["APP", "订单", "地址"],
            },
        ),
        _match(
            doc_id="POLICY_LOG_003",
            title="物流异常处理（地址修改/破损/延迟）",
            text="已发货订单通常不能直接修改地址，需要根据物流状态判断是否可以拦截或改派。",
            score=0.55,
            metadata={
                "intent_ids": ["S16_物流配送"],
                "category": "policy_logistics",
                "keywords": ["改地址", "收货地址", "已经发货", "拦截", "改派"],
            },
        ),
    ]

    result = RuleBasedReranker().rerank(
        "我能改收货地址吗？已经发货了",
        candidates,
        intent_id="S16_物流配送",
    )

    assert result[0].chunk.metadata["doc_id"] == "POLICY_LOG_003"
    signals = {item["name"] for item in result[0].chunk.metadata["rerank_signals"]}
    assert {"intent_match", "policy_term_hit", "domain_term_hit"}.issubset(signals)


def test_reranker_promotes_filter_maintenance_document() -> None:
    candidates = [
        _match(
            doc_id="MANUAL_WATCH_001",
            title="小米手表用户手册",
            text="手表清洁、表盘、充电和系统升级说明。",
            score=0.85,
            metadata={
                "intent_ids": ["S13_保养维护"],
                "category": "manual_product",
                "device_types": ["watch"],
            },
        ),
        _match(
            doc_id="MANUAL_AIR_002",
            title="米家空气净化器滤芯更换指南",
            text="净化器滤芯通常建议 6 到 12 个月更换一次，具体看使用环境和 APP 提醒。",
            score=0.50,
            metadata={
                "intent_ids": ["S13_保养维护"],
                "category": "manual_product",
                "device_types": ["air_purifier"],
                "keywords": ["滤芯", "更换滤芯", "保养", "多久换"],
            },
        ),
    ]

    result = RuleBasedReranker().rerank(
        "净化器滤芯多久换一次？",
        candidates,
        intent_id="S13_保养维护",
    )

    assert result[0].chunk.metadata["doc_id"] == "MANUAL_AIR_002"
    signals = {item["name"] for item in result[0].chunk.metadata["rerank_signals"]}
    assert {"intent_match", "title_keyword_hit", "domain_term_hit"}.issubset(signals)


def test_reranker_adds_explainable_metadata_and_penalizes_short_chunks() -> None:
    candidates = [
        _match(
            doc_id="SHORT_DOC",
            title="保修",
            text="一年。",
            score=0.9,
            metadata={"intent_ids": ["S14_售后政策"], "category": "policy_warranty"},
        ),
        _match(
            doc_id="NORMAL_DOC",
            title="保修期说明",
            text="手机类商品保修期为一年，非人为性能故障可以按售后政策申请免费维修。",
            score=0.8,
            metadata={"intent_ids": ["S14_售后政策"], "category": "policy_warranty"},
        ),
    ]

    result = RuleBasedReranker().rerank(
        "手机保修期多久？",
        candidates,
        intent_id="S14_售后政策",
    )

    assert result[0].chunk.metadata["doc_id"] == "NORMAL_DOC"
    metadata = result[0].chunk.metadata
    assert metadata["rerank_score"] == result[0].score
    assert metadata["rerank_original_score"] == 0.8
    assert isinstance(metadata["rerank_signals"], list)
    short_signals = {item["name"] for item in result[1].chunk.metadata["rerank_signals"]}
    assert "chunk_too_short" in short_signals
