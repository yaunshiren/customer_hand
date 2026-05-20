from __future__ import annotations

from app.rag.documents import KnowledgeChunk
from app.rag.embedding import EmbeddingClient
from app.rag.indexer import RetrievalMatch
from app.rag.retriever import RetrievalResult
from app.rag.vector_store import KnowledgeVectorStore
from app.settings import settings
from app.utils.telemetry import emit_rag_event


class VectorKnowledgeRetriever:
    """向量检索：embed_query → Chroma → 按阈值过滤，返回结构与关键词检索一致。"""

    def __init__(
        self,
        *,
        embedding_client: EmbeddingClient | None = None,
        vector_store: KnowledgeVectorStore | None = None,
        score_threshold: float | None = None,
    ) -> None:
        self.embedding_client = embedding_client or EmbeddingClient.from_env()
        self.vector_store = vector_store or KnowledgeVectorStore.from_settings()
        self.score_threshold = (
            settings.rag_score_threshold if score_threshold is None else score_threshold
        )

    def retrieve(self, query: str, top_k: int | None = None) -> RetrievalResult:
        effective_top_k = top_k if top_k is not None else settings.rag_top_k
        query = query.strip()
        if not query:
            return RetrievalResult(query=query, matches=[])

        embedding = self.embedding_client.embed_query(query)
        if not embedding:
            emit_rag_event(
                "vector_retrieve",
                top_k=effective_top_k,
                match_count=0,
                reason="empty_embedding",
            )
            return RetrievalResult(query=query, matches=[])

        candidate_k = self._candidate_top_k(effective_top_k)
        hits = self.vector_store.query(embedding, top_k=candidate_k)
        filtered = [hit for hit in hits if float(hit["score"]) >= self.score_threshold]
        selected = filtered[:effective_top_k]
        matches = [self._to_retrieval_match(hit) for hit in selected]

        emit_rag_event(
            "vector_retrieve",
            top_k=effective_top_k,
            match_count=len(matches),
            candidate_count=len(hits),
            threshold=self.score_threshold,
            query_len=len(query),
        )
        return RetrievalResult(query=query, matches=matches)

    def _candidate_top_k(self, top_k: int) -> int:
        """多取一些候选再按阈值过滤，降低「取得太少全被滤掉」的概率。"""
        stored = self.vector_store.count()
        if stored <= 0:
            return max(1, top_k)
        return min(stored, max(top_k, top_k * 5))

    def _to_retrieval_match(self, hit: dict) -> RetrievalMatch:
        metadata = dict(hit.get("metadata") or {})
        chunk = KnowledgeChunk(
            chunk_id=str(hit.get("chunk_id") or metadata.get("chunk_id") or ""),
            source=str(hit.get("source") or metadata.get("source") or ""),
            text=str(hit.get("text") or ""),
            metadata=metadata,
        )
        return RetrievalMatch(chunk=chunk, score=float(hit["score"]))
