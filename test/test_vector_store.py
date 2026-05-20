from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

chromadb = pytest.importorskip("chromadb")

from app.rag.vector_store import (  # noqa: E402
    KnowledgeVectorStore,
    VectorChunkRecord,
    distance_to_score,
)


def _unit_vector(axis: int, dim: int = 8) -> list[float]:
    vec = [0.0] * dim
    vec[axis % dim] = 1.0
    return vec


def test_distance_to_score_cosine_convention() -> None:
    assert distance_to_score(0.0) == pytest.approx(1.0)
    assert distance_to_score(1.0) == pytest.approx(0.0)


def test_upsert_and_query_with_fake_vectors(tmp_path: Path) -> None:
    store = KnowledgeVectorStore(persist_dir=tmp_path / "chroma")

    chunks = [
        VectorChunkRecord(
            chunk_id="chunk-return-1",
            text="自签收之日起 7 天内可申请无理由退货",
            embedding=_unit_vector(0),
            metadata={"source": "shop_faq.md", "chunk_index": 0},
        ),
        VectorChunkRecord(
            chunk_id="chunk-refund-1",
            text="退款 1～3 个工作日内发起",
            embedding=_unit_vector(1),
            metadata={"source": "shop_faq.md", "chunk_index": 1},
        ),
        VectorChunkRecord(
            chunk_id="chunk-logistics-1",
            text="物流查询需提供订单号",
            embedding=_unit_vector(2),
            metadata={"source": "logistics.md", "chunk_index": 0},
        ),
    ]
    assert store.upsert(chunks) == 3
    assert store.count() == 3

    hits = store.query(_unit_vector(0), top_k=2)
    assert len(hits) == 2
    assert hits[0]["chunk_id"] == "chunk-return-1"
    assert hits[0]["source"] == "shop_faq.md"
    assert hits[0]["score"] >= hits[1]["score"]
    assert hits[0]["text"].startswith("自签收")


def test_query_empty_index_returns_empty_list(tmp_path: Path) -> None:
    store = KnowledgeVectorStore(persist_dir=tmp_path / "chroma_empty")
    assert store.query(_unit_vector(0), top_k=3) == []
