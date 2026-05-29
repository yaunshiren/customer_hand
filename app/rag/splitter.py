from __future__ import annotations

from typing import Any

from app.rag.documents import KnowledgeChunk


class TextSplitter:
    def __init__(self, chunk_size: int = 400, chunk_overlap: int = 80) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be greater than or equal to 0")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, source: str, text: str, metadata: dict[str, Any] | None = None) -> list[KnowledgeChunk]:
        normalized = self._normalize(text)
        if not normalized:
            return []

        base_metadata = dict(metadata or {})
        doc_id = str(base_metadata.get("doc_id") or self._source_slug(source)).strip()
        if not doc_id:
            doc_id = self._source_slug(source)
        base_metadata.setdefault("doc_id", doc_id)
        base_metadata.setdefault("source", source)

        chunks: list[KnowledgeChunk] = []
        start = 0
        index = 0

        while start < len(normalized):
            end = min(len(normalized), start + self.chunk_size)
            chunk_text = normalized[start:end].strip()

            if chunk_text:
                chunk_metadata = dict(base_metadata)
                chunk_metadata.update(
                    {
                        "doc_id": doc_id,
                        "chunk_index": index,
                        "start": start,
                        "end": end,
                    }
                )
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=f"{doc_id}-{index}",
                        source=source,
                        text=chunk_text,
                        metadata=chunk_metadata,
                    )
                )
                index += 1

            if end >= len(normalized):
                break

            start = end - self.chunk_overlap

        return chunks

    def _normalize(self, text: str) -> str:
        return "\n".join(line.strip() for line in text.splitlines()).strip()

    def _source_slug(self, source: str) -> str:
        normalized = source.replace("\\", "/")
        parts = normalized.rsplit("/", 3)
        tail = "/".join(parts[-3:]) if len(parts) >= 3 else normalized
        slug = tail.rsplit(".", 1)[0]
        return "".join(ch if ch.isalnum() else "-" for ch in slug).strip("-") or "doc"
