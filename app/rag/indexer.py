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
        segments = self._segment_text(text)
        seen: set[str] = set()
        out: list[str] = []
        for segment in segments:
            for token in self._expand_cjk_bigrams(segment):
                if len(token) < 2 or token in seen:
                    continue
                seen.add(token)
                out.append(token)
        return out

    def _segment_text(self, text: str) -> list[str]:
        tokens: list[str] = []
        current: list[str] = []
        for char in text.lower():
            if char.isalnum() or "\u4e00" <= char <= "\u9fff":
                current.append(char)
            else:
                if current:
                    tokens.append("".join(current))
                    current = []
        if current:
            tokens.append("".join(current))
        return tokens

    def _expand_cjk_bigrams(self, token: str) -> list[str]:
        """整段中文会被切成一个词，查询整句与文档子串用二元组做交集，便于中文关键词命中。"""
        expanded = [token]
        if len(token) < 2:
            return expanded
        if not all("\u4e00" <= c <= "\u9fff" for c in token):
            return expanded
        for i in range(len(token) - 1):
            expanded.append(token[i : i + 2])
        return expanded
