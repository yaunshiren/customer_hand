"""验收：假向量 upsert 2～3 条后能 query 命中。在 customer_hand 目录执行：

    python scripts/test_chroma_vector_store.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.vector_store import KnowledgeVectorStore, VectorChunkRecord  # noqa: E402


def _basis(dim: int, index: int) -> list[float]:
    vec = [0.0] * dim
    vec[index] = 1.0
    return vec


def main() -> None:
    dim = 16
    persist_dir = PROJECT_ROOT / "data" / "chroma_smoke"
    store = KnowledgeVectorStore(persist_dir=persist_dir)
    store.reset()

    chunks = [
        VectorChunkRecord(
            chunk_id="smoke-return",
            text="退货规则：7 天内可申请无理由退货",
            embedding=_basis(dim, 0),
            metadata={"source": "shop_faq.md"},
        ),
        VectorChunkRecord(
            chunk_id="smoke-refund",
            text="退款 1～3 个工作日到账",
            embedding=_basis(dim, 1),
            metadata={"source": "shop_faq.md"},
        ),
        VectorChunkRecord(
            chunk_id="smoke-logistics",
            text="查物流需要订单号",
            embedding=_basis(dim, 2),
            metadata={"source": "logistics.md"},
        ),
    ]
    store.upsert(chunks)

    hits = store.query(_basis(dim, 0), top_k=2)
    print("count", store.count())
    for hit in hits:
        print(hit["chunk_id"], hit["score"], hit["source"], hit["text"][:40])

    if not hits or hits[0]["chunk_id"] != "smoke-return":
        raise SystemExit("expected smoke-return as top hit")


if __name__ == "__main__":
    main()
