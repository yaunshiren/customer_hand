from __future__ import annotations

from typing import Any, Iterable

from app.rag.context_builder import ContextBuilder


class CitationBuilder:
    """Build stable citation metadata from retrieval matches."""

    def __init__(self, *, context_builder: ContextBuilder | None = None) -> None:
        self.context_builder = context_builder or ContextBuilder()

    def from_matches(self, matches: Iterable[Any]) -> dict[str, Any]:
        match_list = list(matches)
        records = [_match_record(match) for match in match_list]
        context_doc_ids = [record["doc_id"] for record in records]
        doc_ids = list(dict.fromkeys(doc_id for doc_id in context_doc_ids if doc_id))
        chunk_ids = [record["chunk_id"] for record in records if record["chunk_id"]]
        retrieved_contexts = self.context_builder.build(match_list)

        return {
            "rag_doc_ids": doc_ids,
            "rag_chunk_ids": chunk_ids,
            "rag_context_doc_ids": context_doc_ids,
            "retrieved_contexts": retrieved_contexts,
            "citations": records,
        }


def _match_record(match: Any) -> dict[str, Any]:
    if isinstance(match, dict):
        metadata = dict(match.get("metadata") or {})
        source = str(match.get("source") or metadata.get("source") or "")
        chunk_id = str(match.get("chunk_id") or metadata.get("chunk_id") or "")
        score = match.get("score")
        doc_id = str(match.get("doc_id") or metadata.get("doc_id") or _source_stem(source) or "").strip()
        title = str(match.get("title") or metadata.get("title") or doc_id or chunk_id or "unknown").strip()
    else:
        chunk = getattr(match, "chunk", None)
        metadata = dict(getattr(chunk, "metadata", {}) or {})
        source = str(getattr(chunk, "source", "") or metadata.get("source") or "")
        chunk_id = str(getattr(chunk, "chunk_id", "") or metadata.get("chunk_id") or "")
        score = getattr(match, "score", None)
        doc_id = str(metadata.get("doc_id") or _source_stem(source) or "").strip()
        title = str(metadata.get("title") or doc_id or chunk_id or "unknown").strip()

    return {
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "title": title,
        "source": source,
        "score": float(score) if isinstance(score, (int, float)) else None,
    }


def _source_stem(source: str) -> str:
    normalized = source.replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    name = normalized.rsplit("/", 1)[-1]
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name
