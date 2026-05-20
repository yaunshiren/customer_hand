from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.answerer import KnowledgeAnswerer  # noqa: E402
from app.rag.retriever import (  # noqa: E402
    KeywordKnowledgeRetriever,
    KnowledgeBaseRetriever,
    normalize_rag_backend,
)
from app.settings import settings  # noqa: E402


def test_normalize_rag_backend_aliases() -> None:
    assert normalize_rag_backend("chroma") == "chroma"
    assert normalize_rag_backend("vector") == "chroma"
    assert normalize_rag_backend("keyword") == "keyword"
    assert normalize_rag_backend("unknown-x") == "keyword"


def test_knowledge_base_retriever_keyword_backend() -> None:
    retriever = KnowledgeBaseRetriever(backend="keyword")
    assert retriever.backend == "keyword"
    assert isinstance(retriever._impl, KeywordKnowledgeRetriever)

    result = retriever.retrieve("退货规则", top_k=3)
    assert result.matches


def test_knowledge_base_retriever_chroma_backend_uses_vector_impl() -> None:
    pytest.importorskip("chromadb")
    from app.rag.vector_retriever import VectorKnowledgeRetriever  # noqa: E402

    with patch.object(settings, "rag_backend", "chroma"):
        retriever = KnowledgeBaseRetriever()
    assert retriever.backend == "chroma"
    assert isinstance(retriever._impl, VectorKnowledgeRetriever)


def test_answerer_matches_include_rag_backend_keyword() -> None:
    answerer = KnowledgeAnswerer()
    answerer.retriever = KnowledgeBaseRetriever(backend="keyword")
    result = answerer.answer("退货规则", top_k=3)
    assert result["matches"]
    assert result["matches"][0].get("rag_backend") == "keyword"


def test_answerer_chroma_backend_with_mocked_vector_retrieve() -> None:
    from app.rag.documents import KnowledgeChunk  # noqa: E402
    from app.rag.indexer import RetrievalMatch  # noqa: E402
    from app.rag.retriever import RetrievalResult  # noqa: E402

    fake_match = RetrievalMatch(
        chunk=KnowledgeChunk(
            chunk_id="shop-faq-0",
            source="shop_faq.md",
            text="自签收之日起 7 天内可申请无理由退货",
            metadata={"section": "退货规则"},
        ),
        score=0.88,
    )

    class FakeVectorRetriever:
        backend = "chroma"

        def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
            return RetrievalResult(query=query, matches=[fake_match])

    answerer = KnowledgeAnswerer()
    with patch.object(settings, "rag_backend", "chroma"):
        answerer.retriever = KnowledgeBaseRetriever(backend="chroma")
        answerer.retriever._impl = FakeVectorRetriever()  # type: ignore[assignment]
        result = answerer.answer("退货规则", top_k=3)

    assert result["matches"][0]["rag_backend"] == "chroma"
    assert result["matches"][0]["score"] == pytest.approx(0.88)
    assert "shop_faq" in result["matches"][0]["source"]
