from __future__ import annotations

import time
from typing import Any, Iterator

from dotenv import load_dotenv
from openai import OpenAI

from app.settings import DEFAULT_ENV_FILE, settings
from app.utils.telemetry import emit_rag_event

EMBEDDING_BATCH_SIZE = 10


class EmbeddingDisabledError(RuntimeError):
    """embedding_enabled=false 时调用 embed_* 会抛出此异常，便于测试里 mock 或断言。"""


class EmbeddingClient:
    def __init__(
        self,
        *,
        enabled: bool,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int,
        timeout: float = 30.0,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> None:
        self.enabled = enabled
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout
        self.batch_size = max(1, batch_size)

    @classmethod
    def from_env(cls) -> EmbeddingClient:
        import os

        load_dotenv(DEFAULT_ENV_FILE)

        api_key = (
            os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("BAILIAN_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
        base_url = (
            os.getenv("DASHSCOPE_BASE_URL")
            or os.getenv("BAILIAN_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        timeout = float(os.getenv("LLM_TIMEOUT", "30"))

        return cls(
            enabled=settings.embedding_enabled,
            api_key=api_key,
            base_url=base_url,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout=timeout,
        )

    def embed_query(self, query: str) -> list[float]:
        vectors = self.embed_documents([query])
        if not vectors:
            return []
        return vectors[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not self.enabled:
            raise EmbeddingDisabledError(
                "Embedding API is disabled (EMBEDDING_ENABLED=false). "
                "Enable it in .env or inject a mock EmbeddingClient in tests."
            )

        if not texts:
            return []

        if not self.api_key:
            raise ValueError(
                "Missing DASHSCOPE_API_KEY, BAILIAN_API_KEY, or OPENAI_API_KEY for embedding."
            )

        start_time = time.perf_counter()
        emit_rag_event(
            "embedding.start",
            model=self.model,
            text_count=len(texts),
            dimensions=self.dimensions,
        )

        try:
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            all_vectors: list[list[float]] = []
            for batch in _chunks(texts, self.batch_size):
                response = client.embeddings.create(
                    model=self.model,
                    input=batch,
                    dimensions=self.dimensions,
                    encoding_format="float",
                    timeout=self.timeout,
                )
                ordered = sorted(response.data, key=lambda item: int(item.index))
                all_vectors.extend([list(item.embedding) for item in ordered])

            emit_rag_event(
                "embedding.end",
                model=self.model,
                text_count=len(texts),
                vector_count=len(all_vectors),
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
            return all_vectors
        except Exception as exc:
            emit_rag_event(
                "embedding.error",
                model=self.model,
                error=self._sanitize_error(str(exc)),
            )
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

    def _sanitize_error(self, message: str) -> str:
        for secret in (self.api_key,):
            if secret:
                message = message.replace(secret, "***")
        return message or "embedding request failed"


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
