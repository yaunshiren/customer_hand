"""验收：先 rebuild_index，再查「退货规则」。需有效 API Key 与 EMBEDDING_ENABLED=true。

    python scripts/test_vector_retrieve.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.reindex import rebuild_index  # noqa: E402
from app.rag.vector_retriever import VectorKnowledgeRetriever  # noqa: E402


def main() -> None:
    print("rebuild:", rebuild_index())
    result = VectorKnowledgeRetriever().retrieve("退货规则", top_k=3)
    print("query:", result.query)
    print("matches:", len(result.matches))
    for match in result.matches:
        print(match.score, match.chunk.source, match.chunk.text[:80])

    if not result.matches:
        raise SystemExit("no matches for 退货规则")
    if "shop_faq" not in result.matches[0].chunk.source.replace("\\", "/"):
        raise SystemExit("expected shop_faq.md in top match source")


if __name__ == "__main__":
    main()
