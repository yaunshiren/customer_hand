from __future__ import annotations

import ast
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.rag.documents import KnowledgeChunk, KnowledgeDocumentLoader
from app.rag.indexer import RetrievalMatch
from app.rag.retriever import RetrievalResult
from app.rag.splitter import TextSplitter
from app.settings import settings
from app.utils.telemetry import emit_rag_event


@dataclass(frozen=True)
class _BM25Document:
    chunk: KnowledgeChunk
    term_freqs: Counter[str]
    length: int


class BM25KnowledgeRetriever:
    """Okapi BM25 retriever over local knowledge chunks."""

    def __init__(
        self,
        docs_dir: Path | None = None,
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.docs_dir = docs_dir if docs_dir is not None else settings.knowledge_dir
        self.loader = KnowledgeDocumentLoader()
        self.splitter = TextSplitter()
        self.k1 = k1
        self.b = b
        self.chunks: list[KnowledgeChunk] = []
        self._documents: list[_BM25Document] = []
        self._idf: dict[str, float] = {}
        self._avg_doc_len = 0.0
        self._is_ready = False

    def build(self, docs_dir: Path | None = None) -> None:
        if docs_dir is not None:
            self.docs_dir = docs_dir

        documents = self.loader.load_documents(self.docs_dir)
        chunks: list[KnowledgeChunk] = []
        for document in documents:
            chunks.extend(
                self.splitter.split(
                    document.source,
                    document.text,
                    metadata=document.metadata,
                )
            )

        self.build_from_chunks(chunks)

    def build_from_chunks(self, chunks: Iterable[KnowledgeChunk]) -> None:
        self.chunks = list(chunks)
        self._documents = []
        document_frequency: Counter[str] = Counter()

        for chunk in self.chunks:
            tokens = _chunk_tokens(chunk)
            term_freqs = Counter(tokens)
            length = sum(term_freqs.values())
            self._documents.append(
                _BM25Document(chunk=chunk, term_freqs=term_freqs, length=length)
            )
            document_frequency.update(term_freqs.keys())

        total_docs = len(self._documents)
        total_length = sum(document.length for document in self._documents)
        self._avg_doc_len = total_length / total_docs if total_docs else 0.0
        self._idf = {
            term: math.log(1.0 + (total_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }
        self._is_ready = True

    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
        if not self._is_ready:
            self.build()

        query = query.strip()
        if not query or not self._documents:
            return RetrievalResult(query=query, matches=[])

        query_terms = Counter(_tokenize(query))
        if not query_terms:
            return RetrievalResult(query=query, matches=[])

        scored: list[RetrievalMatch] = []
        for document in self._documents:
            score = self._score_document(query_terms, document)
            if score > 0:
                scored.append(RetrievalMatch(chunk=document.chunk, score=score))

        scored.sort(key=lambda match: match.score, reverse=True)
        matches = scored[: max(0, top_k)]
        emit_rag_event(
            "bm25_retrieve",
            top_k=top_k,
            match_count=len(matches),
            candidate_count=len(scored),
            query_len=len(query),
        )
        return RetrievalResult(query=query, matches=matches)

    def _score_document(
        self,
        query_terms: Counter[str],
        document: _BM25Document,
    ) -> float:
        if document.length <= 0 or self._avg_doc_len <= 0:
            return 0.0

        score = 0.0
        doc_len_norm = 1.0 - self.b + self.b * (document.length / self._avg_doc_len)
        for term, query_freq in query_terms.items():
            term_freq = document.term_freqs.get(term, 0)
            if term_freq <= 0:
                continue
            numerator = term_freq * (self.k1 + 1.0)
            denominator = term_freq + self.k1 * doc_len_norm
            score += self._idf.get(term, 0.0) * (numerator / denominator) * query_freq
        return score


def _chunk_tokens(chunk: KnowledgeChunk) -> list[str]:
    metadata = dict(chunk.metadata or {})
    tokens: list[str] = []
    weighted_fields: tuple[tuple[Any, int], ...] = (
        (chunk.text, 1),
        (metadata.get("doc_id"), 3),
        (metadata.get("title"), 3),
        (metadata.get("keywords"), 2),
        (metadata.get("product_names"), 2),
        (metadata.get("tags"), 2),
        (metadata.get("category"), 1),
        (metadata.get("doc_type"), 1),
        (metadata.get("intent_ids"), 1),
        (metadata.get("related_intents"), 1),
    )
    for value, weight in weighted_fields:
        field_tokens = _tokenize_values(value)
        for _ in range(max(1, weight)):
            tokens.extend(field_tokens)
    return tokens


def _tokenize_values(value: Any) -> list[str]:
    return [
        token
        for text in _metadata_values(value)
        for token in _tokenize(text)
    ]


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


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for segment, kind in _segment_text(str(text)):
        if kind == "cjk":
            tokens.extend(_expand_cjk_segment(segment))
        else:
            tokens.extend(_expand_alnum_segment(segment))
    return [token for token in tokens if token]


def _segment_text(text: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    current: list[str] = []
    current_kind: str | None = None

    def flush() -> None:
        nonlocal current, current_kind
        if current and current_kind:
            segments.append(("".join(current), current_kind))
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

    flush()
    return segments


def _expand_cjk_segment(segment: str) -> list[str]:
    if len(segment) <= 1:
        return [segment]
    tokens = [segment]
    tokens.extend(segment[index : index + 2] for index in range(len(segment) - 1))
    return tokens


def _expand_alnum_segment(segment: str) -> list[str]:
    tokens = [segment]
    tokens.extend(part for part in _split_alpha_digit(segment) if part != segment)
    return tokens


def _split_alpha_digit(segment: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    current_kind: str | None = None

    def flush() -> None:
        nonlocal current, current_kind
        if current:
            parts.append("".join(current))
        current = []
        current_kind = None

    for char in segment:
        kind = "digit" if char.isdigit() else "alpha"
        if current_kind and current_kind != kind:
            flush()
        current_kind = kind
        current.append(char)

    flush()
    return parts
