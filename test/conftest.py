from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTEST_TEMP_ROOT = PROJECT_ROOT / ".pytest_tmp"
PYTEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

# This file is loaded before pytest imports test modules. Establish the complete
# hermetic process environment before app.settings or main can be imported.
os.environ["PYTEST_DEBUG_TEMPROOT"] = str(PYTEST_TEMP_ROOT)
os.environ["CUSTOMER_HAND_DISABLE_DOTENV"] = "1"
os.environ["APP_ENV"] = "test"
os.environ["API_KEY_PRINCIPALS"] = "{}"
os.environ["AUTH_ALLOW_DEV_TOKENS"] = "false"
os.environ["LLM_ENABLED"] = "false"
os.environ["LLM_SMOKE_TEST_ENABLED"] = "false"
os.environ["RAG_BACKEND"] = "keyword"
os.environ["TICKET_STORE_BACKEND"] = "memory"
os.environ["IDEMPOTENCY_BACKEND"] = "memory"
os.environ["RATE_LIMIT_BACKEND"] = "memory"
os.environ["REDIS_URL"] = "redis://127.0.0.1:0/15"
os.environ["CHROMA_PERSIST_DIR"] = str(PYTEST_TEMP_ROOT / "chroma")

MYSQL_INTEGRATION_ENABLED = (
    os.environ.get("RUN_MYSQL_INTEGRATION", "").strip() == "1"
)
if not MYSQL_INTEGRATION_ENABLED:
    os.environ["TRACE_DB_URL"] = ""

EMBEDDING_INTEGRATION_ENABLED = (
    os.environ.get("RUN_EMBEDDING_INTEGRATION", "").strip() == "1"
)
if not EMBEDDING_INTEGRATION_ENABLED:
    os.environ["EMBEDDING_ENABLED"] = "false"
    os.environ["EMBEDDING_PROVIDER"] = "remote"
    os.environ["DASHSCOPE_API_KEY"] = ""
    os.environ["BAILIAN_API_KEY"] = ""
    os.environ["OPENAI_API_KEY"] = ""

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.entry.idempotency import reset_idempotency_store
from app.entry.rate_limit import reset_rate_limiter
from app.settings import Settings, settings


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
    settings_snapshot = deepcopy(settings.model_dump(mode="python"))
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
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "auth_allow_dev_tokens", True)
    if not MYSQL_INTEGRATION_ENABLED:
        monkeypatch.setattr(settings, "trace_db_url", None)
    monkeypatch.setattr(settings, "llm_enabled", False)
    monkeypatch.setattr(
        settings,
        "embedding_enabled",
        EMBEDDING_INTEGRATION_ENABLED,
    )
    monkeypatch.setattr(settings, "rag_backend", "keyword")
    monkeypatch.setattr(settings, "ticket_store_backend", "memory")
    monkeypatch.setattr(settings, "idempotency_backend", "memory")
    monkeypatch.setattr(settings, "rate_limit_backend", "memory")
    reset_rate_limiter()
    reset_idempotency_store()
    yield
    for field_name, value in settings_snapshot.items():
        setattr(settings, field_name, value)
    reset_rate_limiter()
    reset_idempotency_store()


@pytest.fixture
def test_settings() -> Settings:
    """Return a fresh Settings instance with no dotenv source or shared cache."""

    return Settings(_env_file=None)


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
