from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.trace import trace_scope
from app.persistence.db import ping_trace_db, trace_db_session
from app.persistence.models import RetrievalTrace
from app.rag.documents import KnowledgeChunk
from app.rag.hybrid_retriever import HybridRetriever
from app.rag.indexer import RetrievalMatch
from app.rag.retriever import KnowledgeBaseRetriever, RetrievalResult


class FakeKeywordRetriever:
    def __init__(self, matches: list[RetrievalMatch], chunks: list[KnowledgeChunk]) -> None:
        self.matches = matches
        self.chunks = chunks
        self.built = False

    def build(self, docs_dir=None) -> None:
        self.built = True

    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
        return RetrievalResult(query=query, matches=self.matches[:top_k])


class FakeVectorRetriever:
    def __init__(self, matches: list[RetrievalMatch]) -> None:
        self.matches = matches

    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
        return RetrievalResult(query=query, matches=self.matches[:top_k])


def _chunk(doc_id: str, chunk_id: str, text: str, *, intent_id: str | None = None) -> KnowledgeChunk:
    metadata: dict[str, object] = {"doc_id": doc_id, "title": f"{doc_id} title"}
    if intent_id:
        metadata["intent_ids"] = [intent_id]
    return KnowledgeChunk(
        chunk_id=chunk_id,
        source=f"knowledge/{doc_id}.md",
        text=text,
        metadata=metadata,
    )


def _match(doc_id: str, chunk_id: str, score: float, *, intent_id: str | None = None) -> RetrievalMatch:
    return RetrievalMatch(
        chunk=_chunk(doc_id, chunk_id, f"{doc_id} context", intent_id=intent_id),
        score=score,
    )


@pytest.fixture()
def trace_db_available() -> None:
    try:
        ping_trace_db()
    except Exception as exc:  # pragma: no cover - depends on local MySQL.
        pytest.skip(f"trace database is not available: {exc}")


def _trace_id() -> str:
    return f"rag_trace_{uuid.uuid4().hex}"


def _delete_retrieval_traces(trace_id: str) -> None:
    with trace_db_session() as session:
        rows = session.query(RetrievalTrace).filter(RetrievalTrace.trace_id == trace_id).all()
        for row in rows:
            session.delete(row)


def test_hybrid_retriever_emits_channel_and_rerank_trace_payload(monkeypatch) -> None:
    keyword_match = _match("DOC_KEYWORD", "DOC_KEYWORD-0", 12.0)
    vector_match = _match("DOC_VECTOR", "DOC_VECTOR-0", 0.92)
    intent_chunk = _chunk(
        "DOC_INTENT",
        "DOC_INTENT-0",
        "intent context",
        intent_id="S14_售后政策",
    )
    keyword = FakeKeywordRetriever(matches=[keyword_match], chunks=[intent_chunk])
    vector = FakeVectorRetriever(matches=[vector_match])
    captured: dict[str, object] = {}

    def fake_record_retrieval_traces(*, query, records, trace_id=None):
        captured["query"] = query
        captured["records"] = list(records)

    monkeypatch.setattr(
        "app.rag.hybrid_retriever.record_retrieval_traces",
        fake_record_retrieval_traces,
    )

    retriever = HybridRetriever(
        keyword_retriever=keyword,  # type: ignore[arg-type]
        vector_retriever=vector,
    )
    result = retriever.retrieve("售后政策", top_k=2, intent_id="S14_售后政策")

    assert result.matches
    records = captured["records"]
    assert captured["query"] == "售后政策"
    assert {item["channel"] for item in records} == {"bm25", "vector_global", "intent_directed"}
    assert {item["doc_id"] for item in records} == {"DOC_KEYWORD", "DOC_VECTOR", "DOC_INTENT"}
    assert all(item["content"] for item in records)
    assert any(item["rerank_score"] is not None for item in records)
    assert any(item["channel"] == "intent_directed" and item["score"] > 0 for item in records)


def test_keyword_retriever_emits_retrieval_trace_payload(monkeypatch) -> None:
    match = _match("DOC_KEYWORD", "DOC_KEYWORD-0", 6.5)
    captured: dict[str, object] = {}

    class FakeBackend:
        def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
            return RetrievalResult(query=query, matches=[match])

    def fake_record_retrieval_traces(*, query, records, trace_id=None):
        captured["query"] = query
        captured["records"] = list(records)

    monkeypatch.setattr(
        "app.rag.retriever.record_retrieval_traces",
        fake_record_retrieval_traces,
    )

    retriever = KnowledgeBaseRetriever(backend="keyword")
    retriever._impl = FakeBackend()  # type: ignore[assignment]

    result = retriever.retrieve("keyword question", top_k=3)

    assert result.matches == [match]
    records = captured["records"]
    assert captured["query"] == "keyword question"
    assert records == [
        {
            "channel": "keyword",
            "doc_id": "DOC_KEYWORD",
            "chunk_id": "DOC_KEYWORD-0",
            "score": 6.5,
            "rerank_score": None,
            "content": "DOC_KEYWORD context",
        }
    ]


def test_keyword_retriever_persists_retrieval_trace_to_mysql(trace_db_available) -> None:
    trace_id = _trace_id()
    match = _match("DOC_DB", "DOC_DB-0", 7.0)
    _delete_retrieval_traces(trace_id)

    class FakeBackend:
        def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
            return RetrievalResult(query=query, matches=[match])

    retriever = KnowledgeBaseRetriever(backend="keyword")
    retriever._impl = FakeBackend()  # type: ignore[assignment]

    try:
        with trace_scope(trace_id):
            retriever.retrieve("database trace question", top_k=3)

        with trace_db_session() as session:
            rows = list(
                session.execute(
                    select(
                        RetrievalTrace.query,
                        RetrievalTrace.channel,
                        RetrievalTrace.doc_id,
                        RetrievalTrace.chunk_id,
                        RetrievalTrace.score,
                        RetrievalTrace.rerank_score,
                        RetrievalTrace.content,
                    ).where(RetrievalTrace.trace_id == trace_id)
                ).all()
            )

        assert rows == [("database trace question", "keyword", "DOC_DB", "DOC_DB-0", 7.0, None, "DOC_DB context")]
    finally:
        _delete_retrieval_traces(trace_id)
