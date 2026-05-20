from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from app.rag.documents import KnowledgeChunk, KnowledgeDocumentLoader
from app.rag.embedding import EmbeddingClient
from app.rag.splitter import TextSplitter
from app.rag.vector_store import KnowledgeVectorStore, VectorChunkRecord
from app.settings import settings
from app.utils.telemetry import emit_rag_event


def load_knowledge_chunks(docs_dir: Path | None = None) -> list[KnowledgeChunk]:
    directory = docs_dir if docs_dir is not None else settings.knowledge_dir
    loader = KnowledgeDocumentLoader()
    splitter = TextSplitter()

    chunks: list[KnowledgeChunk] = []
    for source, content in loader.load_directory(directory):
        chunks.extend(splitter.split(source, content))
    return chunks


def rebuild_index(
    *,
    docs_dir: Path | None = None,
    embedding_client: EmbeddingClient | None = None,
    vector_store: KnowledgeVectorStore | None = None,
) -> dict[str, Any]:
    """全量重建 Chroma 知识索引（会调用 embedding API 消耗 Token）。"""
    start = time.perf_counter()
    directory = docs_dir if docs_dir is not None else settings.knowledge_dir
    embedder = embedding_client or EmbeddingClient.from_env()
    store = vector_store or KnowledgeVectorStore.from_settings()

    chunks = load_knowledge_chunks(directory)
    document_count = len({chunk.source for chunk in chunks})

    if not chunks:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        emit_rag_event("reindex.end", chunk_count=0, document_count=0, elapsed_ms=elapsed_ms)
        return {
            "success": True,
            "chunk_count": 0,
            "document_count": 0,
            "upserted": 0,
            "elapsed_ms": elapsed_ms,
            "knowledge_dir": str(directory),
            "persist_dir": str(store.persist_dir),
            "embedding_model": embedder.model,
            "embedding_dimensions": embedder.dimensions,
            "message": "no knowledge chunks found",
        }

    texts = [chunk.text for chunk in chunks]
    vectors = embedder.embed_documents(texts)

    if len(vectors) != len(chunks):
        raise RuntimeError(
            f"embedding count mismatch: chunks={len(chunks)} vectors={len(vectors)}"
        )

    store.reset()
    records = [
        VectorChunkRecord(
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            embedding=vector,
            metadata={
                "source": chunk.source,
                **{k: v for k, v in chunk.metadata.items()},
            },
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    upserted = store.upsert(records)
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    result = {
        "success": True,
        "chunk_count": len(chunks),
        "document_count": document_count,
        "upserted": upserted,
        "elapsed_ms": elapsed_ms,
        "knowledge_dir": str(directory),
        "persist_dir": str(store.persist_dir),
        "embedding_model": embedder.model,
        "embedding_dimensions": embedder.dimensions,
        "collection_count": store.count(),
    }
    emit_rag_event(
        "reindex.end",
        chunk_count=result["chunk_count"],
        document_count=result["document_count"],
        elapsed_ms=elapsed_ms,
    )
    return result


def get_index_status(vector_store: KnowledgeVectorStore | None = None) -> dict[str, Any]:
    """索引状态（供后续 GET /api/knowledge/status 使用）。"""
    store = vector_store or KnowledgeVectorStore.from_settings()
    return {
        "chunk_count": store.count(),
        "persist_dir": str(store.persist_dir),
        "collection_name": store.collection_name,
        "rag_backend": settings.rag_backend,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
    }
