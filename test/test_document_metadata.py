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
related_intents:
  - S2
  - S3
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
    assert document.metadata["related_intents"] == ["S2", "S3"]
    assert "屏幕尺寸" in document.text


def test_loader_falls_back_to_filename_without_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "FAQ_FALLBACK_001.md"
    path.write_text("# FAQ\n\n退货规则说明。", encoding="utf-8")

    document = KnowledgeDocumentLoader().load_documents(tmp_path)[0]

    assert document.metadata["doc_id"] == "FAQ_FALLBACK_001"
    assert document.metadata["source"] == str(path)


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
