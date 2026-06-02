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
        self._inverted_index: dict[str, Counter[str]] = {}

    def build(self, chunks: list[KnowledgeChunk]) -> None:
        self._chunks = list(chunks)
        self._inverted_index = {}
        for chunk in chunks:
            self._index_text(chunk.chunk_id, chunk.text, weight=1.0)
            metadata = chunk.metadata or {}
            self._index_text(chunk.chunk_id, metadata.get("doc_id"), weight=2.0)
            self._index_text(chunk.chunk_id, metadata.get("doc_type"), weight=0.8)
            self._index_text(chunk.chunk_id, metadata.get("title"), weight=1.5)
            self._index_text(chunk.chunk_id, metadata.get("related_intents"), weight=1.0)
            self._index_text(chunk.chunk_id, metadata.get("tags"), weight=1.0)
            self._index_text(chunk.chunk_id, metadata.get("intent_ids"), weight=1.2)
            self._index_text(chunk.chunk_id, metadata.get("category"), weight=1.0)
            self._index_text(chunk.chunk_id, metadata.get("product_names"), weight=1.6)
            self._index_text(chunk.chunk_id, metadata.get("device_types"), weight=0.8)
            self._index_text(chunk.chunk_id, metadata.get("keywords"), weight=1.4)

    def search(self, query: str, top_k: int = 3) -> list[RetrievalMatch]:
        if not self._chunks:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores: Counter[str] = Counter()
        for token in query_tokens:
            scores.update(self._inverted_index.get(token, Counter()))

        normalized_query = self._normalize_lookup_text(query)
        for chunk in self._chunks:
            boost = self._metadata_query_boost(chunk, normalized_query)
            if boost:
                scores[chunk.chunk_id] += boost

        matches: list[RetrievalMatch] = []
        chunk_map = {chunk.chunk_id: chunk for chunk in self._chunks}
        for chunk_id, score in scores.most_common(top_k):
            chunk = chunk_map.get(chunk_id)
            if chunk is not None:
                matches.append(RetrievalMatch(chunk=chunk, score=float(score)))

        return matches

    def _index_text(self, chunk_id: str, text: Any, weight: float) -> None:
        if not text:
            return
        for token in self._tokenize(str(text)):
            self._inverted_index.setdefault(token, Counter())[chunk_id] += weight

    def _metadata_query_boost(self, chunk: KnowledgeChunk, normalized_query: str) -> float:
        metadata = chunk.metadata or {}
        title = str(metadata.get("title") or "")
        if not normalized_query:
            return 0.0

        boost = self._fault_doc_boost(metadata, title, normalized_query)
        if not title:
            return boost

        candidates = [title]
        for marker in ("商品详情", "用户手册", "选购指南", "使用手册", "指南", "政策", "规则"):
            if marker in title:
                candidates.append(title.split(marker, 1)[0])

        for candidate in candidates:
            normalized_candidate = self._normalize_lookup_text(candidate)
            if len(normalized_candidate) >= 4 and normalized_candidate in normalized_query:
                boost = max(boost, 12.0 + min(len(normalized_candidate), 12) / 2)
        return boost

    def _fault_doc_boost(self, metadata: dict[str, Any], title: str, normalized_query: str) -> float:
        fault_markers = (
            "故障",
            "异常",
            "坏了",
            "不能",
            "无法",
            "不开机",
            "不进电",
            "充不进电",
            "充不了电",
        )
        if not any(marker in normalized_query for marker in fault_markers):
            return 0.0

        doc_type = str(metadata.get("doc_type") or "").lower()
        title_text = title.lower()
        tags = str(metadata.get("tags") or "").lower()
        boost = 0.0
        if "troubleshooting" in doc_type:
            boost = max(boost, 10.0)
        if "error_code" in doc_type:
            boost = max(boost, 5.0)
        if "故障" in title_text or "排查" in title_text or "故障" in tags:
            boost = max(boost, 8.0)
        return boost

    def _normalize_lookup_text(self, text: str) -> str:
        chars: list[str] = []
        for char in text.lower():
            if "\u4e00" <= char <= "\u9fff" or (char.isascii() and char.isalnum()):
                chars.append(char)
        return "".join(chars)

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
        current_kind: str | None = None

        def flush() -> None:
            nonlocal current, current_kind
            if current:
                tokens.append("".join(current))
                current = []
            current_kind = None

        for char in text.lower():
            if "\u4e00" <= char <= "\u9fff":
                kind = "cjk"
            elif char.isascii() and char.isalnum():
                kind = "alnum"
            else:
                flush()
                continue

            if current_kind and current_kind != kind:
                flush()
            current_kind = kind
            current.append(char)

        if current:
            tokens.append("".join(current))
        return tokens

    def _expand_cjk_bigrams(self, token: str) -> list[str]:
        """整段中文会被切成一个词，查询整句与文档子串用二元组做交集，便于中文关键词命中。"""
        expanded = [token]
        if len(token) < 2:
            return expanded
        if all("\u4e00" <= c <= "\u9fff" for c in token):
            for i in range(len(token) - 1):
                expanded.append(token[i : i + 2])
            return expanded

        if token.isascii() and token.isalnum():
            expanded.extend(self._expand_alnum_parts(token))
        return expanded

    def _expand_alnum_parts(self, token: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        current_kind: str | None = None

        def flush() -> None:
            nonlocal current, current_kind
            if current:
                parts.append("".join(current))
                current = []
            current_kind = None

        for char in token:
            kind = "digit" if char.isdigit() else "alpha"
            if current_kind and current_kind != kind:
                flush()
            current_kind = kind
            current.append(char)

        if current:
            parts.append("".join(current))

        return [part for part in parts if part != token]
