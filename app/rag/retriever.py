from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.rag.documents import KnowledgeChunk, KnowledgeDocumentLoader
from app.rag.indexer import RetrievalMatch, SimpleKeywordIndex
from app.rag.splitter import TextSplitter
from app.settings import settings
from app.utils.telemetry import emit_rag_event

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    query: str
    matches: list[RetrievalMatch]

    @property
    def has_matches(self) -> bool:
        return bool(self.matches)


class _RetrieverBackend(Protocol):
    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult: ...


def normalize_rag_backend(backend: str | None = None) -> str:
    value = (backend if backend is not None else settings.rag_backend).strip().lower()
    if value in {"chroma", "vector"}:
        return "chroma"
    if value in {"hybrid", "mixed", "multi"}:
        return "hybrid"
    if value in {"keyword", "keywords", "lexical"}:
        return "keyword"
    logger.warning("Unknown RAG_BACKEND=%s, fallback to keyword", value)
    return "keyword"


class KeywordKnowledgeRetriever:
    """关键词检索：加载 data/knowledge，内存倒排索引。"""

    def __init__(self, docs_dir: Path | None = None) -> None:
        self.docs_dir = docs_dir if docs_dir is not None else settings.knowledge_dir
        self.loader = KnowledgeDocumentLoader()
        self.splitter = TextSplitter()
        self.index = SimpleKeywordIndex()
        self.chunks: list[KnowledgeChunk] = []
        self._is_ready = False

    def build(self, docs_dir: Path | None = None) -> None:
        if docs_dir is not None:
            self.docs_dir = docs_dir

        documents = self.loader.load_documents(self.docs_dir)
        chunks: list[KnowledgeChunk] = []
        for document in documents:
            chunks.extend(
                self.splitter.split(
                    document.source,
                    document.text,
                    metadata=document.metadata,
                )
            )

        self.chunks = chunks
        self.index.build(chunks)
        self._is_ready = True

    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
        if not self._is_ready:
            self.build()

        matches = self.index.search(query, top_k=top_k)
        return RetrievalResult(query=query, matches=matches)


class KnowledgeBaseRetriever:
    """统一检索入口：按 settings.rag_backend 选择关键词或 Chroma 向量检索。"""

    def __init__(self, docs_dir: Path | None = None, backend: str | None = None) -> None:
        self.backend = normalize_rag_backend(backend)
        self._impl: _RetrieverBackend = self._create_backend(docs_dir)

    def _create_backend(self, docs_dir: Path | None) -> _RetrieverBackend:
        if self.backend == "chroma":
            from app.rag.vector_retriever import VectorKnowledgeRetriever

            return VectorKnowledgeRetriever()
        if self.backend == "hybrid":
            from app.rag.hybrid_retriever import HybridRetriever

            return HybridRetriever(docs_dir=docs_dir)
        return KeywordKnowledgeRetriever(docs_dir=docs_dir)

    def build(self, docs_dir: Path | None = None) -> None:
        build = getattr(self._impl, "build", None)
        if callable(build):
            build(docs_dir)

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        intent_id: str | None = None,
    ) -> RetrievalResult:
        effective_top_k = top_k if top_k is not None else settings.rag_top_k
        if self.backend == "hybrid":
            result = self._impl.retrieve(query, top_k=effective_top_k, intent_id=intent_id)  # type: ignore[call-arg]
        else:
            result = self._impl.retrieve(query, top_k=effective_top_k)
        emit_rag_event(
            "retrieve",
            backend=self.backend,
            top_k=effective_top_k,
            match_count=len(result.matches),
            query_len=len(query.strip()),
        )
        return result
