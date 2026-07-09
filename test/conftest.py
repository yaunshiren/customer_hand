from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Set before app.settings is imported so unit tests never require MySQL implicitly.
os.environ["TICKET_STORE_BACKEND"] = "memory"

from app.settings import settings


class FakeEmbeddingClient:
    """固定向量，CI 不调百炼 API。"""

    def __init__(self, dim: int = 8) -> None:
        self.model = "fake-embedding"
        self.dimensions = dim
        self.enabled = True

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for index, text in enumerate(texts):
            vec = [0.0] * self.dimensions
            vec[index % self.dimensions] = 1.0
            if "退货" in text:
                vec[0] = 1.0
            vectors.append(vec)
        return vectors

    def embed_query(self, query: str) -> list[float]:
        if "退货" in query:
            return self.embed_documents(["退货"])[0]
        return self.embed_documents([query])[0]


@pytest.fixture(autouse=True)
def demo_api_key_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        settings,
        "api_key_principals",
        {
            "demo-user-key": {
                "principal_id": "user_001",
                "tenant_id": "tenant_demo",
                "roles": ["user"],
            },
            "demo-evaluator-key": {
                "principal_id": "evaluator_001",
                "tenant_id": "tenant_demo",
                "roles": ["evaluator"],
            },
            "demo-admin-key": {
                "principal_id": "admin_001",
                "tenant_id": "tenant_demo",
                "roles": ["admin"],
            },
        },
    )
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "auth_allow_dev_tokens", True)
    monkeypatch.setattr(settings, "ticket_store_backend", "memory")


@pytest.fixture
def fake_embedding_client() -> FakeEmbeddingClient:
    return FakeEmbeddingClient()


@pytest.fixture
def integration_embedding_enabled() -> bool:
    if os.getenv("RUN_EMBEDDING_INTEGRATION", "").strip() != "1":
        return False
    key = (
        os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("BAILIAN_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()
    return bool(key)
