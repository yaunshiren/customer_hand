from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.rag.documents import KnowledgeChunk
from app.rag.indexer import RetrievalMatch


CHANNEL_WEIGHTS: dict[str, float] = {
    "keyword": 1.0,
    "vector": 1.0,
    "intent": 0.45,
}


@dataclass
class ChannelMatch:
    channel: str
    match: RetrievalMatch


@dataclass
class MergedMatch:
    chunk: KnowledgeChunk
    score: float = 0.0
    channel_scores: dict[str, float] = field(default_factory=dict)
    raw_scores: dict[str, float] = field(default_factory=dict)

    def to_retrieval_match(self) -> RetrievalMatch:
        metadata = dict(self.chunk.metadata or {})
        metadata["hybrid_channels"] = list(self.channel_scores)
        metadata["hybrid_channel_scores"] = dict(self.channel_scores)
        metadata["hybrid_raw_scores"] = dict(self.raw_scores)
        chunk = KnowledgeChunk(
            chunk_id=self.chunk.chunk_id,
            source=self.chunk.source,
            text=self.chunk.text,
            metadata=metadata,
        )
        return RetrievalMatch(chunk=chunk, score=self.score)


def merge_channel_matches(matches: Iterable[ChannelMatch], top_k: int) -> list[RetrievalMatch]:
    merged: dict[tuple[str, str], MergedMatch] = {}

    for item in matches:
        key = chunk_key(item.match.chunk)
        raw_score = float(item.match.score)
        normalized = normalize_score(item.channel, raw_score)
        weighted = normalized * CHANNEL_WEIGHTS.get(item.channel, 1.0)

        current = merged.get(key)
        if current is None:
            current = MergedMatch(chunk=item.match.chunk)
            merged[key] = current

        current.score += weighted
        current.channel_scores[item.channel] = max(
            current.channel_scores.get(item.channel, 0.0),
            weighted,
        )
        current.raw_scores[item.channel] = max(
            current.raw_scores.get(item.channel, 0.0),
            raw_score,
        )

    ranked = sorted(
        merged.values(),
        key=lambda item: (
            item.score,
            len(item.channel_scores),
            str(item.chunk.metadata.get("title") or ""),
        ),
        reverse=True,
    )
    return [item.to_retrieval_match() for item in ranked[: max(0, top_k)]]


def normalize_score(channel: str, score: float) -> float:
    if channel == "keyword":
        return min(1.0, max(0.0, score / 12.0))
    if channel in {"vector", "intent"}:
        return min(1.0, max(0.0, score))
    return max(0.0, score)


def chunk_key(chunk: KnowledgeChunk) -> tuple[str, str]:
    metadata = chunk.metadata or {}
    doc_id = str(metadata.get("doc_id") or "").strip()
    if not doc_id:
        doc_id = str(chunk.source or "").strip()
    return doc_id, str(chunk.chunk_id or "").strip()


def metadata_matches_intent(metadata: dict[str, Any], intent_id: str | None) -> bool:
    if not intent_id:
        return False

    target = intent_id.strip()
    if not target:
        return False
    target_code = target.split("_", 1)[0]

    values = [
        *_metadata_values(metadata.get("intent_ids")),
        *_metadata_values(metadata.get("related_intents")),
    ]
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        if normalized == target:
            return True
        if normalized == target_code:
            return True
        if normalized.split("_", 1)[0] == target_code:
            return True
    return False


def intent_match_score(metadata: dict[str, Any], intent_id: str | None) -> float:
    if not metadata_matches_intent(metadata, intent_id):
        return 0.0
    if intent_id and intent_id in set(_metadata_values(metadata.get("intent_ids"))):
        return 1.0
    return 0.75


def lexical_overlap_score(query: str, chunk: KnowledgeChunk) -> float:
    query_tokens = set(_cjk_bigrams(query))
    if not query_tokens:
        return 0.0

    metadata = chunk.metadata or {}
    haystack = " ".join(
        [
            str(metadata.get("title") or ""),
            " ".join(_metadata_values(metadata.get("keywords"))),
            chunk.text[:600],
        ]
    )
    haystack_tokens = set(_cjk_bigrams(haystack))
    if not haystack_tokens:
        return 0.0

    overlap = len(query_tokens & haystack_tokens)
    return min(0.35, overlap / max(len(query_tokens), 1))


def _metadata_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = ast.literal_eval(stripped)
            except Exception:
                parsed = None
            if isinstance(parsed, (list, tuple, set)):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [stripped]
    return [str(value).strip()]


def _cjk_bigrams(text: str) -> list[str]:
    normalized = "".join(
        char.lower()
        for char in text
        if "\u4e00" <= char <= "\u9fff" or (char.isascii() and char.isalnum())
    )
    tokens: list[str] = []
    if len(normalized) >= 2:
        tokens.extend(normalized[index : index + 2] for index in range(len(normalized) - 1))
    if normalized:
        tokens.append(normalized)
    return tokens
