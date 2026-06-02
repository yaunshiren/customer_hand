from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class KnowledgeDocument:
    source: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeChunk:
    chunk_id: str
    source: str
    text: str
    metadata: dict[str, Any]


class KnowledgeDocumentLoader:
    def load_documents(self, docs_dir: Path) -> list[KnowledgeDocument]:
        if not docs_dir.exists():
            return []

        documents: list[KnowledgeDocument] = []
        for path in sorted(docs_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".txt", ".md", ".markdown"}:
                continue
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            metadata, text = self._parse_frontmatter(content)
            if "doc_id" not in metadata:
                metadata["doc_id"] = path.stem
            metadata["doc_id"] = str(metadata["doc_id"]).strip() or path.stem
            metadata.setdefault("source", str(path))
            if not self._is_searchable(path, metadata):
                continue
            documents.append(KnowledgeDocument(source=str(path), text=text, metadata=metadata))
        return documents

    def load_directory(self, docs_dir: Path) -> list[tuple[str, str]]:
        return [(document.source, document.text) for document in self.load_documents(docs_dir)]

    def _parse_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        if not content.startswith("---\n") and content != "---":
            return {}, content

        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, content

        end_index = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_index = idx
                break

        if end_index is None:
            return {}, content

        metadata = self._parse_frontmatter_lines(lines[1:end_index])

        body = "\n".join(lines[end_index + 1 :]).strip()
        return metadata, body

    def _parse_frontmatter_lines(self, lines: list[str]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        current_key: str | None = None

        for raw_line in lines:
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if stripped.startswith("-") and current_key:
                value = stripped[1:].strip()
                if not isinstance(metadata.get(current_key), list):
                    metadata[current_key] = []
                metadata[current_key].append(self._clean_value(value))
                continue

            if ":" not in line:
                current_key = None
                continue

            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                current_key = None
                continue

            current_key = key
            metadata[key] = [] if value == "" else self._clean_value(value)

        return metadata

    def _is_searchable(self, path: Path, metadata: dict[str, Any]) -> bool:
        searchable = metadata.get("searchable")
        if isinstance(searchable, bool):
            return searchable
        if isinstance(searchable, str):
            normalized = searchable.strip().lower()
            if normalized in {"false", "no", "0"}:
                return False
            if normalized in {"true", "yes", "1"}:
                return True
        return "_meta" not in path.parts

    def _clean_value(self, value: str) -> Any:
        cleaned = value.strip().strip('"').strip("'")
        lowered = cleaned.lower()
        if lowered in {"true", "yes"}:
            return True
        if lowered in {"false", "no"}:
            return False
        return cleaned
