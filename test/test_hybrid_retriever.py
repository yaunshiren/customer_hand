from __future__ import annotations

import threading
from pathlib import Path

from app.rag.bm25_retriever import BM25KnowledgeRetriever
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
    assert result.matches[0].chunk.metadata["hybrid_channels"] == ["bm25", "vector_global"]
    assert result.matches[0].chunk.metadata["hybrid_raw_scores"]["vector_global"] == 0.9
    assert result.matches[0].chunk.metadata["rerank_score"] == result.matches[0].score


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
    assert "intent_directed" in result.matches[0].chunk.metadata["hybrid_channels"]


def test_bm25_retriever_ranks_by_okapi_score(tmp_path: Path) -> None:
    _write_doc(
        tmp_path / "RETURN_POLICY.md",
        doc_id="RETURN_POLICY",
        intent_id="S15_RETURN",
        title="Return refund policy",
        body="Customers can return items for a refund within seven days.",
    )
    _write_doc(
        tmp_path / "INVOICE_POLICY.md",
        doc_id="INVOICE_POLICY",
        intent_id="S17_INVOICE",
        title="Invoice membership policy",
        body="Members can request invoices and points records.",
    )
    retriever = BM25KnowledgeRetriever(docs_dir=tmp_path)

    result = retriever.retrieve("refund return seven days", top_k=2)

    assert result.matches
    assert result.matches[0].chunk.metadata["doc_id"] == "RETURN_POLICY"
    assert result.matches[0].score > 0


def test_hybrid_executes_retrieval_channels_concurrently() -> None:
    barrier = threading.Barrier(3)
    thread_names: set[str] = set()

    def wait_for_peers() -> None:
        thread_names.add(threading.current_thread().name)
        barrier.wait(timeout=2)

    intent_chunk = KnowledgeChunk(
        chunk_id="DOC_INTENT-0",
        source="knowledge/DOC_INTENT.md",
        text="intent context",
        metadata={"doc_id": "DOC_INTENT", "intent_ids": ["S14_AFTERSALE"]},
    )

    class BlockingBM25Retriever:
        chunks = [intent_chunk]

        def build(self, docs_dir=None) -> None:
            return None

        def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
            wait_for_peers()
            return RetrievalResult(
                query=query,
                matches=[RetrievalMatch(chunk=intent_chunk, score=3.0)],
            )

    class BlockingVectorRetriever:
        def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
            wait_for_peers()
            chunk = KnowledgeChunk(
                chunk_id="DOC_VECTOR-0",
                source="knowledge/DOC_VECTOR.md",
                text="vector context",
                metadata={"doc_id": "DOC_VECTOR"},
            )
            return RetrievalResult(
                query=query,
                matches=[RetrievalMatch(chunk=chunk, score=0.9)],
            )

    class BlockingHybridRetriever(HybridRetriever):
        def _retrieve_by_intent(
            self,
            *,
            query: str,
            intent_id: str | None,
            top_k: int,
        ) -> list[RetrievalMatch]:
            wait_for_peers()
            return [RetrievalMatch(chunk=intent_chunk, score=1.0)]

    retriever = BlockingHybridRetriever(
        bm25_retriever=BlockingBM25Retriever(),
        vector_retriever=BlockingVectorRetriever(),
    )

    result = retriever.retrieve("after sale policy", top_k=3, intent_id="S14_AFTERSALE")

    assert result.matches
    assert len(thread_names) == 3
    assert all(name.startswith("rag_channel") for name in thread_names)
