from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class KnowledgeChunk:
    chunk_id: str
    source: str
    text: str
    metadata: dict[str, Any]


class KnowledgeDocumentLoader:
    def load_directory(self, docs_dir: Path) -> list[tuple[str, str]]:
        if not docs_dir.exists():
            return []

        documents: list[tuple[str, str]] = []
        for path in sorted(docs_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".txt", ".md", ".markdown"}:
                continue
            content = path.read_text(encoding="utf-8").strip()
            if content:
                documents.append((str(path), content))
        return documents
