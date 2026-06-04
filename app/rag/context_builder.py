from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ContextBlock:
    index: int
    doc_id: str
    chunk_id: str
    title: str
    content: str
    source: str

    def format(self) -> str:
        return "\n".join(
            [
                f"[来源 {self.index}]",
                f"doc_id: {self.doc_id}",
                f"chunk_id: {self.chunk_id}",
                f"title: {self.title}",
                f"content: {self.content}",
            ]
        )


class ContextBuilder:
    """Build stable, citation-friendly RAG context blocks for prompts and eval metadata."""

    def __init__(self, *, max_content_chars: int = 1200) -> None:
        self.max_content_chars = max(200, max_content_chars)

    def build(self, matches: Iterable[Any]) -> list[str]:
        return [block.format() for block in self.build_blocks(matches)]

    def build_text(self, matches: Iterable[Any]) -> str:
        return "\n\n".join(self.build(matches))

    def build_blocks(self, matches: Iterable[Any]) -> list[ContextBlock]:
        blocks: list[ContextBlock] = []
        for index, match in enumerate(matches, start=1):
            record = _match_record(match)
            content = _truncate(record["text"], self.max_content_chars)
            blocks.append(
                ContextBlock(
                    index=index,
                    doc_id=record["doc_id"],
                    chunk_id=record["chunk_id"],
                    title=record["title"],
                    content=content,
                    source=record["source"],
                )
            )
        return blocks


def _match_record(match: Any) -> dict[str, str]:
    if isinstance(match, dict):
        metadata = dict(match.get("metadata") or {})
        source = str(match.get("source") or metadata.get("source") or "")
        chunk_id = str(match.get("chunk_id") or metadata.get("chunk_id") or "")
        text = str(match.get("text") or metadata.get("text") or "")
        doc_id = str(match.get("doc_id") or metadata.get("doc_id") or _source_stem(source) or "").strip()
        title = str(match.get("title") or metadata.get("title") or doc_id or chunk_id or "unknown").strip()
    else:
        chunk = getattr(match, "chunk", None)
        metadata = dict(getattr(chunk, "metadata", {}) or {})
        source = str(getattr(chunk, "source", "") or metadata.get("source") or "")
        chunk_id = str(getattr(chunk, "chunk_id", "") or metadata.get("chunk_id") or "")
        text = str(getattr(chunk, "text", "") or metadata.get("text") or "")
        doc_id = str(metadata.get("doc_id") or _source_stem(source) or "").strip()
        title = str(metadata.get("title") or doc_id or chunk_id or "unknown").strip()

    return {
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "title": title,
        "source": source,
        "text": _normalize_content(text),
    }


def _normalize_content(text: str) -> str:
    lines = [line.strip() for line in str(text).replace("\r\n", "\n").splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 20].rstrip()}... [truncated]"


def _source_stem(source: str) -> str:
    normalized = source.replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    name = normalized.rsplit("/", 1)[-1]
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name
