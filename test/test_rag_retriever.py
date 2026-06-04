from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.answerer import KnowledgeAnswerer  # noqa: E402


def test_knowledge_answerer_defaults_to_project_knowledge_dir() -> None:
    from app.rag.retriever import KnowledgeBaseRetriever  # noqa: E402

    answerer = KnowledgeAnswerer()
    answerer.retriever = KnowledgeBaseRetriever(backend="keyword")
    result = answerer.answer("退货规则", top_k=3)
    assert result["matches"], "应加载 data/knowledge 并命中退货规则相关片段"
    assert result["rag_doc_ids"]
    assert result["rag_chunk_ids"]
    assert result["retrieved_contexts"][0].startswith("[来源 1]")
