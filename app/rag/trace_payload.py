from __future__ import annotations

from typing import Any

from app.rag.indexer import RetrievalMatch


def retrieval_trace_record(
    *,
    channel: str,
    match: RetrievalMatch,
    rerank_score: float | None = None,
) -> dict[str, Any]:
    return {
        "channel": channel,
        "doc_id": _doc_id(match),
        "chunk_id": str(match.chunk.chunk_id or "").strip() or None,
        "score": float(match.score),
        "rerank_score": _coerce_score(rerank_score),
        "content": match.chunk.text,
    }


def rerank_scores_by_chunk_key(matches: list[RetrievalMatch]) -> dict[tuple[str, str], float]:
    scores: dict[tuple[str, str], float] = {}
    for match in matches:
        metadata = dict(match.chunk.metadata or {})
        value = metadata.get("rerank_score", match.score)
        score = _coerce_score(value)
        if score is not None:
            scores[chunk_trace_key(match)] = score
    return scores


def chunk_trace_key(match: RetrievalMatch) -> tuple[str, str]:
    metadata = dict(match.chunk.metadata or {})
    doc_id = str(metadata.get("doc_id") or "").strip()
    if not doc_id:
        doc_id = str(match.chunk.source or "").strip()
    return doc_id, str(match.chunk.chunk_id or "").strip()


def _doc_id(match: RetrievalMatch) -> str | None:
    metadata = dict(match.chunk.metadata or {})
    value = str(metadata.get("doc_id") or "").strip()
    if value:
        return value
    source = str(match.chunk.source or "").strip()
    return source or None


def _coerce_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
