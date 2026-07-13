from __future__ import annotations

from pathlib import Path

import pytest

import app.settings as settings_module
from app.entry.idempotency_store import InMemoryIdempotencyStore
from app.entry.rate_limit_store import InMemoryRateLimiter
from app.rag.embedding import EmbeddingClient, EmbeddingDisabledError
from app.settings import Settings, settings


@pytest.mark.parametrize("env_file_exists", [True, False])
def test_test_settings_ignore_dotenv_whether_file_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env_file_exists: bool,
) -> None:
    candidate = tmp_path / ("present.env" if env_file_exists else "missing.env")
    if env_file_exists:
        candidate.write_text(
            "APP_ENV=production\n"
            "TRACE_DB_URL=mysql+pymysql://developer:secret@127.0.0.1/dev\n"
            "LLM_ENABLED=true\n"
            "EMBEDDING_ENABLED=true\n"
            "RAG_BACKEND=chroma\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(settings_module, "DEFAULT_ENV_FILE", candidate)
    monkeypatch.setattr(
        settings_module,
        "load_dotenv",
        lambda *_args, **_kwargs: pytest.fail("dotenv must not be read by pytest"),
    )

    assert settings_module.runtime_env_file() is None
    assert settings_module.load_runtime_dotenv() is False
    configured = Settings(_env_file=settings_module.runtime_env_file())
    assert configured.app_env == "test"
    assert configured.trace_db_url in {None, ""}
    assert configured.llm_enabled is False
    assert configured.embedding_enabled is False
    assert configured.rag_backend == "keyword"


def test_global_and_fresh_test_settings_use_safe_backends(test_settings: Settings) -> None:
    for configured in (settings, test_settings):
        assert configured.app_env == "test"
        assert configured.trace_db_url in {None, ""}
        assert configured.llm_enabled is False
        assert configured.embedding_enabled is False
        assert configured.rag_backend == "keyword"
        assert configured.ticket_store_backend == "memory"
        assert configured.idempotency_backend == "memory"
        assert configured.rate_limit_backend == "memory"
    assert Settings.model_config.get("env_file") is None


def test_llm_and_embedding_env_loaders_do_not_read_dotenv_or_call_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_module,
        "load_dotenv",
        lambda *_args, **_kwargs: pytest.fail("dotenv must not be read by clients"),
    )
    monkeypatch.setattr(
        "app.llm.client.OpenAI",
        lambda *_args, **_kwargs: pytest.fail("OpenAI client must not be created"),
    )
    monkeypatch.setattr(
        "app.rag.embedding.OpenAI",
        lambda *_args, **_kwargs: pytest.fail("Embedding client must not be created"),
    )

    from app.llm.client import LLMClient

    llm = LLMClient.from_env()
    assert llm.enabled is False
    assert llm.generate_json("system", "user")["error"] == "LLM disabled"

    embedding = EmbeddingClient.from_env()
    assert embedding.enabled is False
    with pytest.raises(EmbeddingDisabledError):
        embedding.embed_query("must stay local")


def test_application_factory_does_not_initialize_external_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.entry.idempotency as idempotency
    import app.entry.rate_limit as rate_limit
    import app.persistence.db as persistence_db
    import app.rag.vector_store as vector_store
    from main import create_app

    monkeypatch.setattr(persistence_db, "_engine", None)
    monkeypatch.setattr(persistence_db, "_session_factory", None)
    monkeypatch.setattr(
        persistence_db,
        "create_engine",
        lambda *_args, **_kwargs: pytest.fail("MySQL engine must not be created"),
    )
    monkeypatch.setattr(
        rate_limit,
        "RedisRateLimiter",
        lambda *_args, **_kwargs: pytest.fail("Redis rate limiter must not be created"),
    )
    monkeypatch.setattr(
        idempotency,
        "RedisIdempotencyStore",
        lambda *_args, **_kwargs: pytest.fail("Redis idempotency store must not be created"),
    )
    monkeypatch.setattr(
        vector_store.chromadb,
        "PersistentClient",
        lambda *_args, **_kwargs: pytest.fail("Chroma client must not be created"),
    )

    assert isinstance(rate_limit.build_rate_limiter(), InMemoryRateLimiter)
    assert isinstance(idempotency.build_idempotency_store(), InMemoryIdempotencyStore)

    application = create_app()
    assert persistence_db._engine is None
    assert persistence_db._session_factory is None
    assert application.state.agent.memory_service is None
    assert application.state.agent.llm_generator.client.enabled is False
    assert application.state.agent.knowledge_answerer.llm.enabled is False
    assert application.state.agent.knowledge_answerer.retriever.backend == "keyword"


def test_fresh_settings_are_not_cached_across_environment_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings(_env_file=None).llm_enabled is False

    with monkeypatch.context() as isolated:
        isolated.setenv("LLM_ENABLED", "true")
        isolated.setenv("TICKET_STORE_BACKEND", "mysql")
        modified = Settings(_env_file=None)
        assert modified.llm_enabled is True
        assert modified.ticket_store_backend == "mysql"

    restored = Settings(_env_file=None)
    assert restored.llm_enabled is False
    assert restored.ticket_store_backend == "memory"


def test_pytest_registers_and_excludes_integration_markers_by_default(
    pytestconfig: pytest.Config,
) -> None:
    markers = "\n".join(pytestconfig.getini("markers"))
    assert "integration:" in markers
    assert "mysql:" in markers
    assert "redis:" in markers
    assert "external:" in markers
    assert "not integration" in " ".join(pytestconfig.getini("addopts"))
