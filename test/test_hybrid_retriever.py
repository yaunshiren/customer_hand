from __future__ import annotations

from pathlib import Path

from app.rag.documents import KnowledgeChunk
from app.rag.hybrid_retriever import HybridRetriever
from app.rag.indexer import RetrievalMatch
from app.rag.retriever import RetrievalResult


class EmptyVectorRetriever:
    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
        return RetrievalResult(query=query, matches=[])


def _write_doc(path: Path, doc_id: str, intent_id: str, title: str, body: str) -> None:
    path.write_text(
        f"""---
doc_id: {doc_id}
doc_type: policy
title: {title}
category: policy_test
searchable: true
intent_ids:
  - {intent_id}
keywords:
  - 保修期
---

# {title}

{body}
""",
        encoding="utf-8",
    )


def test_hybrid_merges_keyword_and_vector_duplicates(tmp_path: Path) -> None:
    doc_path = tmp_path / "POLICY_WAR_TEST.md"
    _write_doc(
        doc_path,
        doc_id="POLICY_WAR_TEST",
        intent_id="S14_售后政策",
        title="保修政策",
        body="小米 14 Pro 保修期是一年。",
    )

    class DuplicateVectorRetriever:
        def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
            chunk = KnowledgeChunk(
                chunk_id="POLICY_WAR_TEST-0",
                source=str(doc_path),
                text="小米 14 Pro 保修期是一年。",
                metadata={"doc_id": "POLICY_WAR_TEST", "title": "保修政策"},
            )
            return RetrievalResult(query=query, matches=[RetrievalMatch(chunk=chunk, score=0.9)])

    retriever = HybridRetriever(
        docs_dir=tmp_path,
        vector_retriever=DuplicateVectorRetriever(),
    )

    result = retriever.retrieve("小米 14 Pro 保修期多久", top_k=3)

    assert len([m for m in result.matches if m.chunk.metadata["doc_id"] == "POLICY_WAR_TEST"]) == 1
    assert result.matches[0].chunk.metadata["hybrid_channels"] == ["keyword", "vector"]
    assert result.matches[0].score > 0.9


def test_hybrid_intent_directed_recall_uses_intent_metadata(tmp_path: Path) -> None:
    _write_doc(
        tmp_path / "POLICY_WAR_TEST.md",
        doc_id="POLICY_WAR_TEST",
        intent_id="S14_售后政策",
        title="保修政策",
        body="不同品类的保修期说明。",
    )
    _write_doc(
        tmp_path / "POLICY_OTHER_TEST.md",
        doc_id="POLICY_OTHER_TEST",
        intent_id="S6_配件兼容",
        title="配件政策",
        body="充电器和配件兼容说明。",
    )
    retriever = HybridRetriever(
        docs_dir=tmp_path,
        vector_retriever=EmptyVectorRetriever(),
    )

    result = retriever.retrieve("多久", intent_id="S14_售后政策", top_k=3)

    assert result.matches
    assert result.matches[0].chunk.metadata["doc_id"] == "POLICY_WAR_TEST"
    assert "intent" in result.matches[0].chunk.metadata["hybrid_channels"]
