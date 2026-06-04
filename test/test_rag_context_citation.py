from __future__ import annotations

from pathlib import Path

from app.rag.citation import CitationBuilder
from app.rag.context_builder import ContextBuilder
from app.rag.documents import KnowledgeChunk
from app.rag.indexer import RetrievalMatch


def _match(doc_id: str, chunk_id: str, text: str, score: float = 0.8) -> RetrievalMatch:
    return RetrievalMatch(
        chunk=KnowledgeChunk(
            chunk_id=chunk_id,
            source=str(Path("knowledge") / f"{doc_id}.md"),
            text=text,
            metadata={"doc_id": doc_id, "title": f"{doc_id} 标题"},
        ),
        score=score,
    )


def test_context_builder_formats_matches_for_prompt() -> None:
    builder = ContextBuilder(max_content_chars=200)

    contexts = builder.build(
        [
            _match("POLICY_WAR_001", "POLICY-WAR-001-003", "保修期为 12 个月。\n\n以激活时间为准。"),
        ]
    )

    assert contexts == [
        "\n".join(
            [
                "[来源 1]",
                "doc_id: POLICY_WAR_001",
                "chunk_id: POLICY-WAR-001-003",
                "title: POLICY_WAR_001 标题",
                "content: 保修期为 12 个月。\n以激活时间为准。",
            ]
        )
    ]


def test_context_builder_supports_serialized_match_dicts() -> None:
    builder = ContextBuilder()

    contexts = builder.build(
        [
            {
                "chunk_id": "LOG-001-001",
                "source": "knowledge/logistics.md",
                "text": "已发货后需要根据物流状态判断是否可拦截。",
                "metadata": {"doc_id": "POLICY_LOG_001", "title": "物流政策"},
            }
        ]
    )

    assert contexts[0].startswith("[来源 1]\ndoc_id: POLICY_LOG_001\n")
    assert "title: 物流政策" in contexts[0]
    assert "content: 已发货后需要根据物流状态判断是否可拦截。" in contexts[0]


def test_context_builder_truncates_long_content() -> None:
    builder = ContextBuilder(max_content_chars=200)

    contexts = builder.build([_match("DOC_LONG", "DOC-LONG-001", "很长" * 200)])

    assert len(contexts[0]) < 320
    assert "[truncated]" in contexts[0]


def test_citation_builder_returns_stable_metadata() -> None:
    builder = CitationBuilder()

    metadata = builder.from_matches(
        [
            _match("DOC_A", "DOC-A-001", "第一段", score=0.9),
            _match("DOC_A", "DOC-A-002", "第二段", score=0.7),
            _match("DOC_B", "DOC-B-001", "第三段", score=0.5),
        ]
    )

    assert metadata["rag_doc_ids"] == ["DOC_A", "DOC_B"]
    assert metadata["rag_chunk_ids"] == ["DOC-A-001", "DOC-A-002", "DOC-B-001"]
    assert metadata["rag_context_doc_ids"] == ["DOC_A", "DOC_A", "DOC_B"]
    assert len(metadata["retrieved_contexts"]) == 3
    assert metadata["retrieved_contexts"][0].startswith("[来源 1]\ndoc_id: DOC_A\n")
    assert metadata["citations"][0] == {
        "doc_id": "DOC_A",
        "chunk_id": "DOC-A-001",
        "title": "DOC_A 标题",
        "source": str(Path("knowledge") / "DOC_A.md"),
        "score": 0.9,
    }
