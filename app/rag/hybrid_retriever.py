from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

from app.rag.bm25_retriever import BM25KnowledgeRetriever
from app.rag.indexer import RetrievalMatch
from app.rag.reranker import RuleBasedReranker
from app.rag.retriever import RetrievalResult
from app.rag.scoring import (
    ChannelMatch,
    intent_match_score,
    lexical_overlap_score,
    merge_channel_matches,
)
from app.rag.trace_payload import chunk_trace_key, rerank_scores_by_chunk_key, retrieval_trace_record
from app.persistence.retrieval_recorder import record_retrieval_traces
from app.settings import settings
from app.utils.telemetry import emit_rag_event

logger = logging.getLogger(__name__)


class _VectorRetrieverLike(Protocol):
    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult: ...


class _BM25RetrieverLike(Protocol):
    chunks: list[Any]

    def build(self, docs_dir: Path | None = None) -> None: ...

    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult: ...


class HybridRetriever:
    """Multi-channel retriever: BM25 + global vector + intent-directed metadata recall."""

    backend = "hybrid"

    def __init__(
        self,
        docs_dir: Path | None = None,
        *,
        bm25_retriever: _BM25RetrieverLike | None = None,
        keyword_retriever: _BM25RetrieverLike | None = None,
        vector_retriever: _VectorRetrieverLike | None = None,
        reranker: RuleBasedReranker | None = None,
        enable_vector: bool = True,
        channel_workers: int = 3,
    ) -> None:
        self.bm25_retriever = (
            bm25_retriever
            or keyword_retriever
            or BM25KnowledgeRetriever(docs_dir=docs_dir)
        )
        self.keyword_retriever = self.bm25_retriever
        self._vector_retriever = vector_retriever
        self.reranker = reranker or RuleBasedReranker()
        self.enable_vector = enable_vector
        self.channel_workers = max(1, channel_workers)

    def build(self, docs_dir: Path | None = None) -> None:
        self.bm25_retriever.build(docs_dir)

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
        channel_results = self._retrieve_channels_concurrently(
            query=query,
            intent_id=intent_id,
            top_k=candidate_k,
        )
        channel_matches = [
            ChannelMatch(channel=channel, match=match)
            for channel, matches in channel_results.items()
            for match in matches
        ]

        merged_matches = merge_channel_matches(channel_matches, top_k=candidate_k)
        matches = self.reranker.rerank(
            query=query,
            candidates=merged_matches,
            intent_id=intent_id,
            top_k=effective_top_k,
        )
        self._record_retrieval_trace(
            query=query,
            channel_matches=channel_matches,
            final_matches=matches,
        )
        emit_rag_event(
            "hybrid_retrieve",
            top_k=effective_top_k,
            candidate_count=len(channel_matches),
            merged_count=len(merged_matches),
            match_count=len(matches),
            bm25_count=len(channel_results.get("bm25", [])),
            vector_global_count=len(channel_results.get("vector_global", [])),
            intent_directed_count=len(channel_results.get("intent_directed", [])),
            has_intent=bool(intent_id),
            query_len=len(query),
        )
        return RetrievalResult(query=query, matches=matches)

    def _retrieve_channels_concurrently(
        self,
        *,
        query: str,
        intent_id: str | None,
        top_k: int,
    ) -> dict[str, list[RetrievalMatch]]:
        self._ensure_bm25_ready()
        max_workers = min(self.channel_workers, 3)
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rag_channel") as executor:
            futures: dict[str, Future[Any]] = {
                "bm25": executor.submit(self._retrieve_bm25, query=query, top_k=top_k),
                "vector_global": executor.submit(self._retrieve_vector, query=query, top_k=top_k),
                "intent_directed": executor.submit(
                    self._retrieve_by_intent,
                    query=query,
                    intent_id=intent_id,
                    top_k=top_k,
                ),
            }
            return {
                channel: self._resolve_channel_result(channel, future)
                for channel, future in futures.items()
            }

    def _resolve_channel_result(
        self,
        channel: str,
        future: Future[Any],
    ) -> list[RetrievalMatch]:
        try:
            result = future.result()
        except Exception as exc:
            logger.warning("hybrid channel %s skipped: %s", channel, exc)
            emit_rag_event("hybrid_channel_skip", channel=channel, reason=str(exc)[:200])
            return []
        if isinstance(result, RetrievalResult):
            return result.matches
        return list(result or [])

    def _retrieve_bm25(self, query: str, top_k: int) -> RetrievalResult:
        try:
            return self.bm25_retriever.retrieve(query, top_k=top_k)
        except Exception as exc:
            logger.warning("hybrid bm25 channel skipped: %s", exc)
            emit_rag_event(
                "hybrid_bm25_skip",
                reason=str(exc)[:200],
                top_k=top_k,
                query_len=len(query),
            )
            return RetrievalResult(query=query, matches=[])

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

    def _ensure_bm25_ready(self) -> None:
        if getattr(self.bm25_retriever, "chunks", None):
            return
        build = getattr(self.bm25_retriever, "build", None)
        if callable(build):
            build()

    def _retrieve_by_intent(
        self,
        *,
        query: str,
        intent_id: str | None,
        top_k: int,
    ) -> list[RetrievalMatch]:
        if not intent_id:
            return []

        self._ensure_bm25_ready()

        matches: list[RetrievalMatch] = []
        for chunk in self.bm25_retriever.chunks:
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

    def _record_retrieval_trace(
        self,
        *,
        query: str,
        channel_matches: list[ChannelMatch],
        final_matches: list[RetrievalMatch],
    ) -> None:
        rerank_by_key = rerank_scores_by_chunk_key(final_matches)
        records = [
            retrieval_trace_record(
                channel=item.channel,
                match=item.match,
                rerank_score=rerank_by_key.get(chunk_trace_key(item.match)),
            )
            for item in channel_matches
        ]
        record_retrieval_traces(query=query, records=records)
