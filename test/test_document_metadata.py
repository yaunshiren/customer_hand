from __future__ import annotations

from pathlib import Path

from app.rag.documents import KnowledgeChunk
from app.rag.documents import KnowledgeDocumentLoader
from app.rag.indexer import SimpleKeywordIndex
from app.rag.splitter import TextSplitter


def test_loader_reads_frontmatter_metadata(tmp_path: Path) -> None:
    path = tmp_path / "PROD_TEST_001.md"
    path.write_text(
        """---
doc_id: PROD_TEST_001
doc_type: product_detail
title: 测试商品
category: product
searchable: true
related_intents:
  - S2
  - S3
intent_ids:
  - S2_参数咨询
product_names:
  - 小米 14 Pro
device_types:
  - phone
keywords:
  - 屏幕
  - 刷新率
---

# 正文

屏幕尺寸为 6.73 英寸。
""",
        encoding="utf-8",
    )

    document = KnowledgeDocumentLoader().load_documents(tmp_path)[0]

    assert document.metadata["doc_id"] == "PROD_TEST_001"
    assert document.metadata["doc_type"] == "product_detail"
    assert document.metadata["title"] == "测试商品"
    assert document.metadata["category"] == "product"
    assert document.metadata["searchable"] is True
    assert document.metadata["related_intents"] == ["S2", "S3"]
    assert document.metadata["intent_ids"] == ["S2_参数咨询"]
    assert document.metadata["product_names"] == ["小米 14 Pro"]
    assert document.metadata["device_types"] == ["phone"]
    assert document.metadata["keywords"] == ["屏幕", "刷新率"]
    assert "屏幕尺寸" in document.text


def test_loader_falls_back_to_filename_without_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "FAQ_FALLBACK_001.md"
    path.write_text("# FAQ\n\n退货规则说明。", encoding="utf-8")

    document = KnowledgeDocumentLoader().load_documents(tmp_path)[0]

    assert document.metadata["doc_id"] == "FAQ_FALLBACK_001"
    assert document.metadata["source"] == str(path)


def test_loader_skips_unsearchable_documents(tmp_path: Path) -> None:
    searchable = tmp_path / "POLICY_KEEP_001.md"
    searchable.write_text(
        """---
doc_id: POLICY_KEEP_001
doc_type: policy
title: 可检索文档
searchable: true
---

# 可检索
""",
        encoding="utf-8",
    )
    hidden = tmp_path / "PROGRESS.md"
    hidden.write_text(
        """---
doc_id: PROGRESS
doc_type: meta
title: 进度文档
searchable: false
---

# 不应进入检索
""",
        encoding="utf-8",
    )

    documents = KnowledgeDocumentLoader().load_documents(tmp_path)

    assert [document.metadata["doc_id"] for document in documents] == ["POLICY_KEEP_001"]


def test_loader_skips_meta_directory_by_default(tmp_path: Path) -> None:
    meta_dir = tmp_path / "_meta"
    meta_dir.mkdir()
    (meta_dir / "progress.md").write_text("# 进度\n\n不应进入检索。", encoding="utf-8")
    (tmp_path / "FAQ_KEEP_001.md").write_text("# FAQ\n\n应该进入检索。", encoding="utf-8")

    documents = KnowledgeDocumentLoader().load_documents(tmp_path)

    assert [document.metadata["doc_id"] for document in documents] == ["FAQ_KEEP_001"]


def test_splitter_propagates_document_metadata() -> None:
    chunks = TextSplitter(chunk_size=12, chunk_overlap=2).split(
        "fake.md",
        "0123456789abcdef",
        metadata={"doc_id": "DOC_001", "title": "测试文档"},
    )

    assert chunks
    assert chunks[0].chunk_id == "DOC_001-0"
    assert chunks[0].metadata["doc_id"] == "DOC_001"
    assert chunks[0].metadata["title"] == "测试文档"
    assert chunks[0].metadata["source"] == "fake.md"
    assert "start" in chunks[0].metadata
    assert "end" in chunks[0].metadata


def test_keyword_index_boosts_exact_product_title_metadata() -> None:
    target = KnowledgeChunk(
        chunk_id="PROD_PHONE_004-0",
        source="phone.md",
        text="screen size refresh rate",
        metadata={
            "doc_id": "PROD_PHONE_004",
            "title": "\u5c0f\u7c73 14 Pro \u5546\u54c1\u8be6\u60c5",
        },
    )
    competitor = KnowledgeChunk(
        chunk_id="PROD_PHONE_002-0",
        source="phone13.md",
        text="screen size refresh rate",
        metadata={
            "doc_id": "PROD_PHONE_002",
            "title": "\u5c0f\u7c73 13 Pro \u5546\u54c1\u8be6\u60c5",
        },
    )

    index = SimpleKeywordIndex()
    index.build([competitor, target])

    matches = index.search(
        "\u5c0f\u7c73 14 Pro \u7684\u5c4f\u5e55\u5c3a\u5bf8\u548c\u5237\u65b0\u7387",
        top_k=2,
    )

    assert matches[0].chunk.chunk_id == "PROD_PHONE_004-0"


def test_keyword_index_boosts_troubleshooting_docs_for_fault_queries() -> None:
    troubleshooting = KnowledgeChunk(
        chunk_id="FAQ_VAC_001-0",
        source="faq.md",
        text="\u626b\u5730\u673a \u5145\u7535 \u7535\u6c60 \u89e6\u70b9",
        metadata={
            "doc_id": "FAQ_VAC_001",
            "doc_type": "troubleshooting",
            "title": "\u77f3\u5934\u626b\u5730\u673a\u5e38\u89c1\u6545\u969c\u6392\u67e5",
        },
    )
    product = KnowledgeChunk(
        chunk_id="PROD_VAC_001-0",
        source="product.md",
        text="\u626b\u5730\u673a \u5145\u7535 \u7535\u6c60 \u89e6\u70b9",
        metadata={
            "doc_id": "PROD_VAC_001",
            "doc_type": "product_detail",
            "title": "\u77f3\u5934\u626b\u5730\u673a\u5668\u4eba T7 \u5546\u54c1\u8be6\u60c5",
        },
    )

    index = SimpleKeywordIndex()
    index.build([product, troubleshooting])

    matches = index.search("\u6211\u7684\u626b\u5730\u673a\u5145\u4e0d\u8fdb\u7535\u4e86", top_k=2)

    assert matches[0].chunk.chunk_id == "FAQ_VAC_001-0"


def test_keyword_index_reads_retrieval_metadata_fields() -> None:
    policy = KnowledgeChunk(
        chunk_id="POLICY_WAR_001-0",
        source="policy.md",
        text="售后服务说明",
        metadata={
            "doc_id": "POLICY_WAR_001",
            "doc_type": "policy",
            "title": "比特严选保修政策总则",
            "intent_ids": ["S14_售后政策"],
            "category": "policy_warranty",
            "device_types": ["phone"],
            "keywords": ["保修期", "免费维修"],
        },
    )
    product = KnowledgeChunk(
        chunk_id="PROD_PHONE_004-0",
        source="phone.md",
        text="小米 14 Pro 商品参数",
        metadata={
            "doc_id": "PROD_PHONE_004",
            "doc_type": "product_detail",
            "title": "小米 14 Pro 商品详情",
            "product_names": ["小米 14 Pro"],
            "device_types": ["phone"],
        },
    )
    index = SimpleKeywordIndex()
    index.build([product, policy])

    matches = index.search("保修期 免费维修", top_k=2)

    assert matches[0].chunk.chunk_id == "POLICY_WAR_001-0"


def test_priority_knowledge_docs_have_retrieval_metadata() -> None:
    knowledge_root = Path(__file__).resolve().parents[1] / "data" / "knowledge" / "bitselect"
    documents = KnowledgeDocumentLoader().load_documents(knowledge_root)
    docs_by_id = {document.metadata["doc_id"]: document.metadata for document in documents}

    assert "META_PROGRESS" not in docs_by_id

    priority_doc_ids = {
        "POLICY_WAR_001",
        "POLICY_RET_004",
        "POLICY_LOG_003",
        "MANUAL_VAC_001",
        "NET_GUIDE_001",
        "FAQ_VAC_001",
        "CODE_PHONE_001",
        "PROD_PHONE_004",
    }
    for doc_id in priority_doc_ids:
        metadata = docs_by_id[doc_id]
        assert metadata["category"]
        assert metadata["searchable"] is True
        assert metadata["intent_ids"]
        assert metadata["keywords"]
