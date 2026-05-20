from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection

from app.settings import settings
from app.utils.telemetry import emit_rag_event

# 全项目固定 collection 名，便于 reindex / 查询共用同一索引。
COLLECTION_NAME = "knowledge_chunks"

# Chroma HNSW 空间：cosine。返回的 distance 为 cosine distance（越小越相似）。
CHROMA_SPACE = "cosine"


@dataclass
class VectorChunkRecord:
    """写入 Chroma 的一条 chunk。"""

    chunk_id: str
    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


def distance_to_score(distance: float) -> float:
    """将 Chroma cosine distance 转为对外 score。

    - Chroma（hnsw:space=cosine）：distance = 1 - cosine_similarity，范围约 [0, 2]，**越小越相似**。
    - 本项目对外约定：**score 越大越相似**，与 `settings.rag_score_threshold` 同向（阈值越高要求越严）。
    - 换算：score = 1 - distance；对浮点误差做 clamp 到 [0, 1]。
    """
    return max(0.0, min(1.0, 1.0 - float(distance)))


class KnowledgeVectorStore:
    def __init__(
        self,
        *,
        persist_dir: Path,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = self._get_or_create_collection()

    @classmethod
    def from_settings(cls) -> KnowledgeVectorStore:
        return cls(persist_dir=settings.chroma_persist_dir)

    def upsert(self, chunks: list[VectorChunkRecord]) -> int:
        if not chunks:
            return 0

        ids: list[str] = []
        documents: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, Any]] = []

        for chunk in chunks:
            ids.append(chunk.chunk_id)
            documents.append(chunk.text)
            embeddings.append(list(chunk.embedding))
            metadatas.append(self._normalize_metadata(chunk.metadata, chunk.text))

        self._collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        emit_rag_event(
            "vector_store.upsert",
            collection=self.collection_name,
            chunk_count=len(chunks),
        )
        return len(chunks)

    def query(self, embedding: list[float], top_k: int = 3) -> list[dict[str, Any]]:
        if not embedding or top_k <= 0:
            return []

        n_results = max(1, top_k)
        count = self._collection.count()
        if count == 0:
            return []
        n_results = min(n_results, count)

        result = self._collection.query(
            query_embeddings=[list(embedding)],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        hits = self._parse_query_result(result)
        emit_rag_event(
            "vector_store.query",
            collection=self.collection_name,
            top_k=top_k,
            hit_count=len(hits),
        )
        return hits

    def count(self) -> int:
        return int(self._collection.count())

    def reset(self) -> None:
        """删除并重建 collection，供 reindex 全量覆盖使用。"""
        try:
            self._client.delete_collection(self.collection_name)
        except Exception:
            pass
        self._collection = self._get_or_create_collection()
        emit_rag_event("vector_store.reset", collection=self.collection_name)

    def _get_or_create_collection(self) -> Collection:
        return self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": CHROMA_SPACE},
        )

    def _normalize_metadata(self, metadata: dict[str, Any], text: str) -> dict[str, Any]:
        meta = dict(metadata or {})
        source = str(meta.get("source") or meta.get("file") or "").strip()
        if source:
            meta["source"] = source
        meta.setdefault("chunk_id", meta.get("chunk_id", ""))
        if not meta.get("chunk_id"):
            meta.pop("chunk_id", None)
        # Chroma metadata 值仅支持 str/int/float/bool，其余转字符串。
        return {key: self._coerce_metadata_value(value) for key, value in meta.items()}

    def _coerce_metadata_value(self, value: Any) -> str | int | float | bool:
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    def _parse_query_result(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits: list[dict[str, Any]] = []
        for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
            meta = dict(metadata or {})
            source = str(meta.get("source") or "")
            text = str(document or meta.get("text") or "")
            score = distance_to_score(float(distance))
            hits.append(
                {
                    "chunk_id": str(chunk_id),
                    "text": text,
                    "source": source,
                    "score": score,
                    "distance": float(distance),
                    "metadata": meta,
                }
            )

        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits
