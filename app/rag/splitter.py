from __future__ import annotations

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

    def split(self, source: str, text: str) -> list[KnowledgeChunk]:
        normalized = self._normalize(text)
        if not normalized:
            return []

        chunks: list[KnowledgeChunk] = []
        start = 0
        index = 0

        while start < len(normalized):
            end = min(len(normalized), start + self.chunk_size)
            chunk_text = normalized[start:end].strip()

            if chunk_text:
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=f"{self._source_slug(source)}-{index}",
                        source=source,
                        text=chunk_text,
                        metadata={
                            "chunk_index": index,
                            "start": start,
                            "end": end,
                        },
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
        slug = source.replace("\\", "/").rsplit("/", 1)[-1]
        slug = slug.rsplit(".", 1)[0]
        return "".join(ch if ch.isalnum() else "-" for ch in slug).strip("-") or "doc"