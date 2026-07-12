from __future__ import annotations

import time
from typing import Any, Iterator

from openai import OpenAI

from app.settings import load_runtime_dotenv, settings
from app.utils.telemetry import emit_rag_event

EMBEDDING_BATCH_SIZE = 10

try:  # Optional dependency: only required when EMBEDDING_PROVIDER=local.
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - exercised through explicit local-mode error path.
    SentenceTransformer = None  # type: ignore[assignment]


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
        provider: str = "remote",
        local_device: str | None = None,
        local_query_instruction: str = "",
        timeout: float = 30.0,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> None:
        self.enabled = enabled
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.dimensions = dimensions
        self.provider = self._normalize_provider(provider)
        self.local_device = local_device
        self.local_query_instruction = local_query_instruction
        self.timeout = timeout
        self.batch_size = max(1, batch_size)
        self._local_model: Any | None = None

    @classmethod
    def from_env(cls) -> EmbeddingClient:
        import os

        load_runtime_dotenv()

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
        provider = settings.embedding_provider.strip().lower()

        if cls._normalize_provider(provider) == "local":
            return cls(
                enabled=settings.embedding_enabled,
                api_key="",
                base_url="",
                model=settings.local_embedding_model,
                dimensions=settings.local_embedding_dimensions,
                provider="local",
                local_device=settings.local_embedding_device,
                local_query_instruction=settings.local_embedding_query_instruction,
                timeout=timeout,
            )

        return cls(
            enabled=settings.embedding_enabled,
            api_key=api_key,
            base_url=base_url,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            provider="remote",
            timeout=timeout,
        )

    def embed_query(self, query: str) -> list[float]:
        if self.provider == "local":
            text = query
            if self.local_query_instruction:
                text = f"{self.local_query_instruction}{query}"
            vectors = self.embed_documents([text])
            if not vectors:
                return []
            return vectors[0]

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

        if self.provider == "local":
            return self._embed_documents_local(texts)

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

    @classmethod
    def _normalize_provider(cls, provider: str) -> str:
        value = (provider or "remote").strip().lower()
        if value in {"remote", "api", "openai", "dashscope", "bailian"}:
            return "remote"
        if value in {"local", "sentence-transformers", "sentence_transformers"}:
            return "local"
        raise ValueError(f"Unknown embedding provider: {provider}")

    def _embed_documents_local(self, texts: list[str]) -> list[list[float]]:
        start_time = time.perf_counter()
        emit_rag_event(
            "embedding.start",
            provider="local",
            model=self.model,
            text_count=len(texts),
            dimensions=self.dimensions,
        )

        try:
            model = self._get_local_model()
            encoded = model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            vectors = _to_vector_list(encoded)
            emit_rag_event(
                "embedding.end",
                provider="local",
                model=self.model,
                text_count=len(texts),
                vector_count=len(vectors),
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )
            return vectors
        except Exception as exc:
            emit_rag_event(
                "embedding.error",
                provider="local",
                model=self.model,
                error=self._sanitize_error(str(exc)),
            )
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

    def _get_local_model(self) -> Any:
        if self._local_model is not None:
            return self._local_model
        if SentenceTransformer is None:
            raise RuntimeError(
                "sentence-transformers is required for local embedding. "
                "Install it with `pip install sentence-transformers`."
            )

        kwargs: dict[str, Any] = {}
        if self.local_device:
            kwargs["device"] = self.local_device
        self._local_model = SentenceTransformer(self.model, **kwargs)
        return self._local_model

    def _sanitize_error(self, message: str) -> str:
        for secret in (self.api_key,):
            if secret:
                message = message.replace(secret, "***")
        return message or "embedding request failed"


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _to_vector_list(encoded: Any) -> list[list[float]]:
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    return [[float(value) for value in vector] for vector in encoded]
