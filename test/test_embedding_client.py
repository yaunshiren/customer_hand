from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.embedding import (  # noqa: E402
    EMBEDDING_BATCH_SIZE,
    EmbeddingClient,
    EmbeddingDisabledError,
)


def _make_item(index: int, dim: int) -> MagicMock:
    item = MagicMock()
    item.index = index
    item.embedding = [float(index)] * dim
    return item


def test_embed_documents_batches_more_than_ten() -> None:
    client = EmbeddingClient(
        enabled=True,
        api_key="test-key",
        base_url="https://example.com/v1",
        model="text-embedding-v4",
        dimensions=4,
        batch_size=EMBEDDING_BATCH_SIZE,
    )
    texts = [f"text-{i}" for i in range(11)]

    mock_response_1 = MagicMock()
    mock_response_1.data = [_make_item(i, 4) for i in range(10)]
    mock_response_2 = MagicMock()
    mock_response_2.data = [_make_item(0, 4)]

    with patch("app.rag.embedding.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.embeddings.create.side_effect = [mock_response_1, mock_response_2]

        vectors = client.embed_documents(texts)

    assert len(vectors) == 11
    assert mock_client.embeddings.create.call_count == 2
    first_call = mock_client.embeddings.create.call_args_list[0].kwargs
    assert len(first_call["input"]) == 10
    assert first_call["dimensions"] == 4


def test_embed_query_returns_first_vector() -> None:
    client = EmbeddingClient(
        enabled=True,
        api_key="test-key",
        base_url="https://example.com/v1",
        model="text-embedding-v4",
        dimensions=3,
    )
    mock_response = MagicMock()
    mock_response.data = [_make_item(0, 3)]

    with patch("app.rag.embedding.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.embeddings.create.return_value = mock_response

        vec = client.embed_query("退货规则")

    assert len(vec) == 3
    assert vec[0] == 0.0


def test_embed_raises_when_disabled() -> None:
    client = EmbeddingClient(
        enabled=False,
        api_key="test-key",
        base_url="https://example.com/v1",
        model="text-embedding-v4",
        dimensions=1024,
    )
    with pytest.raises(EmbeddingDisabledError):
        client.embed_query("退货规则")


def test_error_message_redacts_api_key() -> None:
    client = EmbeddingClient(
        enabled=True,
        api_key="sk-secret-key-12345",
        base_url="https://example.com/v1",
        model="text-embedding-v4",
        dimensions=1024,
    )
    with patch("app.rag.embedding.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value.embeddings.create.side_effect = RuntimeError(
            "auth failed sk-secret-key-12345"
        )
        with pytest.raises(RuntimeError, match="\\*\\*\\*"):
            client.embed_documents(["hello"])
