from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.rag.documents import KnowledgeChunk, KnowledgeDocumentLoader
from app.rag.indexer import RetrievalMatch, SimpleKeywordIndex
from app.rag.splitter import TextSplitter


@dataclass
class RetrievalResult:
    query: str
    matches: list[RetrievalMatch]

    @property
    def has_matches(self) -> bool:
        return bool(self.matches)


class KnowledgeBaseRetriever:
    def __init__(self, docs_dir: Path | None = None) -> None:
        self.docs_dir = docs_dir
        self.loader = KnowledgeDocumentLoader()
        self.splitter = TextSplitter()
        self.index = SimpleKeywordIndex()
        self._is_ready = False

    def build(self, docs_dir: Path | None = None) -> None:
        if docs_dir is not None:
            self.docs_dir = docs_dir

        if self.docs_dir is None:
            self._is_ready = False
            return

        documents = self.loader.load_directory(self.docs_dir)
        chunks: list[KnowledgeChunk] = []
        for source, content in documents:
            chunks.extend(self.splitter.split(source, content))

        self.index.build(chunks)
        self._is_ready = True

    def retrieve(self, query: str, top_k: int = 3) -> RetrievalResult:
        if not self._is_ready:
            self.build()

        matches = self.index.search(query, top_k=top_k)
        return RetrievalResult(query=query, matches=matches)
