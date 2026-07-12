from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

pytest.importorskip("chromadb")

from app.rag.answerer import KnowledgeAnswerer  # noqa: E402
from app.rag.reindex import get_index_status, load_knowledge_chunks, rebuild_index  # noqa: E402
from app.rag.retriever import KnowledgeBaseRetriever  # noqa: E402
from app.rag.vector_retriever import VectorKnowledgeRetriever  # noqa: E402
from app.rag.vector_store import KnowledgeVectorStore, VectorChunkRecord  # noqa: E402
from app.settings import settings  # noqa: E402
from conftest import FakeEmbeddingClient  # noqa: E402

ANSWER_REQUIRED_KEYS = frozenset(
    {
        "answer",
        "matches",
        "used_llm",
        "rag_doc_ids",
        "rag_chunk_ids",
        "rag_context_doc_ids",
        "retrieved_contexts",
    }
)
MATCH_REQUIRED_KEYS = frozenset(
    {"chunk_id", "source", "score", "text", "metadata", "rag_backend"}
)


def _assert_match_fields(match: dict) -> None:
    assert MATCH_REQUIRED_KEYS.issubset(match.keys())
    assert isinstance(match["score"], (int, float))
    assert match["rag_backend"] in {"chroma", "keyword", "hybrid"}


def _assert_answer_shape(result: dict) -> None:
    assert ANSWER_REQUIRED_KEYS.issubset(result.keys())
    assert isinstance(result["answer"], str)
    assert isinstance(result["matches"], list)
    assert isinstance(result["used_llm"], bool)


@pytest.fixture
def chroma_store(tmp_path: Path) -> KnowledgeVectorStore:
    return KnowledgeVectorStore(persist_dir=tmp_path / "chroma")


def test_load_knowledge_chunks_reads_shop_faq() -> None:
    chunks = load_knowledge_chunks(PROJECT_ROOT / "data" / "knowledge")
    assert chunks
    assert any("退货" in chunk.text for chunk in chunks)


def test_rebuild_index_with_mocked_embedding(chroma_store: KnowledgeVectorStore) -> None:
    result = rebuild_index(
        docs_dir=PROJECT_ROOT / "data" / "knowledge",
        embedding_client=FakeEmbeddingClient(),
        vector_store=chroma_store,
    )

    assert result["success"] is True
    assert result["chunk_count"] > 0
    assert result["upserted"] == result["chunk_count"]
    assert chroma_store.count() == result["chunk_count"]
    status = get_index_status(vector_store=chroma_store)
    assert status["chunk_count"] == result["chunk_count"]


def test_vector_retriever_hit_and_threshold(chroma_store: KnowledgeVectorStore) -> None:
    embedder = FakeEmbeddingClient(dim=4)
    chroma_store.upsert(
        [
            VectorChunkRecord(
                chunk_id="return-1",
                text="自签收之日起 7 天内可申请无理由退货",
                embedding=[1.0, 0.0, 0.0, 0.0],
                metadata={"source": "shop_faq.md", "section": "退货规则"},
            ),
            VectorChunkRecord(
                chunk_id="other-1",
                text="物流查询需要订单号",
                embedding=[0.0, 1.0, 0.0, 0.0],
                metadata={"source": "logistics.md"},
            ),
        ]
    )

    retriever = VectorKnowledgeRetriever(
        embedding_client=embedder,
        vector_store=chroma_store,
        score_threshold=0.0,
    )
    hit = retriever.retrieve("退货规则", top_k=2)
    assert hit.matches
    assert hit.matches[0].score >= hit.matches[-1].score
    assert "退货" in hit.matches[0].chunk.text

    strict = VectorKnowledgeRetriever(
        embedding_client=embedder,
        vector_store=chroma_store,
        score_threshold=0.99,
    )
    filtered = strict.retrieve("退货", top_k=3)
    assert len(filtered.matches) == 1
    assert filtered.matches[0].chunk.chunk_id == "return-1"


def test_vector_retriever_no_hit_when_index_empty(tmp_path: Path) -> None:
    store = KnowledgeVectorStore(persist_dir=tmp_path / "chroma_empty")
    store.reset()
    retriever = VectorKnowledgeRetriever(
        embedding_client=FakeEmbeddingClient(),
        vector_store=store,
        score_threshold=0.45,
    )
    result = retriever.retrieve("退货规则", top_k=3)
    assert result.matches == []


def test_knowledge_answerer_chroma_mocked_pipeline(
    chroma_store: KnowledgeVectorStore,
    fake_embedding_client: FakeEmbeddingClient,
) -> None:
    with (
        patch.object(settings, "rag_backend", "chroma"),
        patch(
            "app.rag.vector_retriever.EmbeddingClient.from_env",
            return_value=fake_embedding_client,
        ),
        patch(
            "app.rag.vector_store.KnowledgeVectorStore.from_settings",
            return_value=chroma_store,
        ),
    ):
        rebuild_index(
            docs_dir=PROJECT_ROOT / "data" / "knowledge",
            embedding_client=fake_embedding_client,
            vector_store=chroma_store,
        )
        result = KnowledgeAnswerer().answer("退货规则", top_k=3)

    _assert_answer_shape(result)
    assert result["matches"], "应命中知识库"
    _assert_match_fields(result["matches"][0])
    assert result["matches"][0]["rag_backend"] == "chroma"
    assert 0.0 <= float(result["matches"][0]["score"]) <= 1.0


def test_knowledge_answerer_no_hit_fallback(
    chroma_store: KnowledgeVectorStore,
    fake_embedding_client: FakeEmbeddingClient,
) -> None:
    chroma_store.reset()

    with (
        patch.object(settings, "rag_backend", "chroma"),
        patch(
            "app.rag.vector_retriever.EmbeddingClient.from_env",
            return_value=fake_embedding_client,
        ),
        patch(
            "app.rag.vector_store.KnowledgeVectorStore.from_settings",
            return_value=chroma_store,
        ),
        patch.object(settings, "rag_score_threshold", 0.45),
    ):
        result = KnowledgeAnswerer().answer("完全无关的外星语 xyz", top_k=3)

    _assert_answer_shape(result)
    assert result["matches"] == []
    assert result["used_llm"] is False
    assert "暂时没有找到相关知识" in result["answer"]


def test_knowledge_answerer_signature_unchanged_with_llm_disabled() -> None:
    with patch("app.rag.answerer.LLMClient.from_env") as mock_llm_factory:
        mock_llm = mock_llm_factory.return_value
        mock_llm.generate_json.return_value = {
            "success": False,
            "raw_output": "",
        }
        with patch.object(settings, "rag_backend", "keyword"):
            result = KnowledgeAnswerer().answer("退货规则", top_k=3)

    _assert_answer_shape(result)
    assert result["matches"]
    assert "llm_result" not in result or result.get("used_llm") is False


def test_knowledge_base_retriever_chroma_delegates_to_vector(
    chroma_store: KnowledgeVectorStore,
    fake_embedding_client: FakeEmbeddingClient,
) -> None:
    chroma_store.upsert(
        [
            VectorChunkRecord(
                chunk_id="c1",
                text="退货 7 天内",
                embedding=fake_embedding_client.embed_query("退货"),
                metadata={"source": "shop_faq.md"},
            )
        ]
    )
    with (
        patch.object(settings, "rag_backend", "chroma"),
        patch(
            "app.rag.vector_retriever.EmbeddingClient.from_env",
            return_value=fake_embedding_client,
        ),
        patch(
            "app.rag.vector_store.KnowledgeVectorStore.from_settings",
            return_value=chroma_store,
        ),
    ):
        result = KnowledgeBaseRetriever().retrieve("退货规则", top_k=1)

    assert result.matches
    assert result.matches[0].score <= 1.0


@pytest.mark.integration
@pytest.mark.external
def test_rebuild_and_retrieve_integration(integration_embedding_enabled: bool) -> None:
    if not integration_embedding_enabled:
        pytest.skip("设置 RUN_EMBEDDING_INTEGRATION=1 且配置 DASHSCOPE_API_KEY 后运行")

    from app.rag.embedding import EmbeddingClient  # noqa: E402

    if not EmbeddingClient.from_env().enabled:
        pytest.skip("EMBEDDING_ENABLED=false")

    result = rebuild_index()
    assert result["success"] is True
    assert result["chunk_count"] > 0

    with patch.object(settings, "rag_backend", "chroma"):
        retrieval = KnowledgeBaseRetriever().retrieve("退货规则", top_k=3)

    assert retrieval.matches
    assert any("shop_faq" in m.chunk.source.replace("\\", "/") for m in retrieval.matches)
