from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from app.rag.indexer import RetrievalMatch
from app.rag.retriever import KeywordKnowledgeRetriever, RetrievalResult
from app.rag.scoring import (
    ChannelMatch,
    intent_match_score,
    lexical_overlap_score,
    merge_channel_matches,
)
from app.settings import settings
from app.utils.telemetry import emit_rag_event

logger = logging.getLogger(__name__)


class _VectorRetrieverLike(Protocol):
    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult: ...


class HybridRetriever:
    """Multi-channel retriever: keyword + vector + intent-directed metadata recall."""

    backend = "hybrid"

    def __init__(
        self,
        docs_dir: Path | None = None,
        *,
        keyword_retriever: KeywordKnowledgeRetriever | None = None,
        vector_retriever: _VectorRetrieverLike | None = None,
        enable_vector: bool = True,
    ) -> None:
        self.keyword_retriever = keyword_retriever or KeywordKnowledgeRetriever(docs_dir=docs_dir)
        self._vector_retriever = vector_retriever
        self.enable_vector = enable_vector

    def build(self, docs_dir: Path | None = None) -> None:
        self.keyword_retriever.build(docs_dir)

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        intent_id: str | None = None,
    ) -> RetrievalResult:
        effective_top_k = top_k if top_k is not None else settings.rag_top_k
        query = query.strip()
        if not query:
            return RetrievalResult(query=query, matches=[])

        candidate_k = self._candidate_top_k(effective_top_k)
        channel_matches: list[ChannelMatch] = []

        keyword_result = self.keyword_retriever.retrieve(query, top_k=candidate_k)
        channel_matches.extend(
            ChannelMatch(channel="keyword", match=match) for match in keyword_result.matches
        )

        vector_result = self._retrieve_vector(query=query, top_k=candidate_k)
        channel_matches.extend(
            ChannelMatch(channel="vector", match=match) for match in vector_result.matches
        )

        intent_matches = self._retrieve_by_intent(
            query=query,
            intent_id=intent_id,
            top_k=candidate_k,
        )
        channel_matches.extend(ChannelMatch(channel="intent", match=match) for match in intent_matches)

        matches = merge_channel_matches(channel_matches, top_k=effective_top_k)
        emit_rag_event(
            "hybrid_retrieve",
            top_k=effective_top_k,
            candidate_count=len(channel_matches),
            match_count=len(matches),
            keyword_count=len(keyword_result.matches),
            vector_count=len(vector_result.matches),
            intent_count=len(intent_matches),
            has_intent=bool(intent_id),
            query_len=len(query),
        )
        return RetrievalResult(query=query, matches=matches)

    def _retrieve_vector(self, query: str, top_k: int) -> RetrievalResult:
        if not self.enable_vector:
            return RetrievalResult(query=query, matches=[])

        try:
            retriever = self._get_vector_retriever()
            return retriever.retrieve(query, top_k=top_k)
        except Exception as exc:
            logger.warning("hybrid vector channel skipped: %s", exc)
            emit_rag_event(
                "hybrid_vector_skip",
                reason=str(exc)[:200],
                top_k=top_k,
                query_len=len(query),
            )
            return RetrievalResult(query=query, matches=[])

    def _get_vector_retriever(self) -> _VectorRetrieverLike:
        if self._vector_retriever is None:
            from app.rag.vector_retriever import VectorKnowledgeRetriever

            self._vector_retriever = VectorKnowledgeRetriever()
        return self._vector_retriever

    def _retrieve_by_intent(
        self,
        *,
        query: str,
        intent_id: str | None,
        top_k: int,
    ) -> list[RetrievalMatch]:
        if not intent_id:
            return []

        if not self.keyword_retriever.chunks:
            self.keyword_retriever.build()

        matches: list[RetrievalMatch] = []
        for chunk in self.keyword_retriever.chunks:
            metadata = chunk.metadata or {}
            score = intent_match_score(metadata, intent_id)
            if score <= 0:
                continue
            score += lexical_overlap_score(query, chunk)
            matches.append(RetrievalMatch(chunk=chunk, score=score))

        matches.sort(key=lambda match: match.score, reverse=True)
        return matches[:top_k]

    def _candidate_top_k(self, top_k: int) -> int:
        return max(top_k, top_k * 4, 8)
