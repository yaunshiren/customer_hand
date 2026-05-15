from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.rag.documents import KnowledgeChunk


@dataclass
class RetrievalMatch:
    chunk: KnowledgeChunk
    score: float


class SimpleKeywordIndex:
    def __init__(self) -> None:
        self._chunks: list[KnowledgeChunk] = []
        self._inverted_index: dict[str, set[str]] = {}

    def build(self, chunks: list[KnowledgeChunk]) -> None:
        self._chunks = list(chunks)
        self._inverted_index = {}
        for chunk in chunks:
            for token in self._tokenize(chunk.text):
                self._inverted_index.setdefault(token, set()).add(chunk.chunk_id)

    def search(self, query: str, top_k: int = 3) -> list[RetrievalMatch]:
        if not self._chunks:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores: Counter[str] = Counter()
        for token in query_tokens:
            for chunk_id in self._inverted_index.get(token, set()):
                scores[chunk_id] += 1

        matches: list[RetrievalMatch] = []
        chunk_map = {chunk.chunk_id: chunk for chunk in self._chunks}
        for chunk_id, score in scores.most_common(top_k):
            chunk = chunk_map.get(chunk_id)
            if chunk is not None:
                matches.append(RetrievalMatch(chunk=chunk, score=float(score)))

        return matches

    def _tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        current = []
        for char in text.lower():
            if char.isalnum() or "\u4e00" <= char <= "\u9fff":
                current.append(char)
            else:
                if current:
                    tokens.append("".join(current))
                    current = []
        if current:
            tokens.append("".join(current))
        return [token for token in tokens if len(token) >= 2]
