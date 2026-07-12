from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import app  # noqa: E402
from app.entry.idempotency import reset_idempotency_store  # noqa: E402
from app.entry.rate_limit import reset_rate_limiter  # noqa: E402
from app.settings import settings  # noqa: E402

client = TestClient(app)
AUTH_ADMIN = {
    "Authorization": "Bearer demo-admin-key",
    "Idempotency-Key": "knowledge-reindex-keyword-backend",
}


@pytest.fixture(autouse=True)
def reset_entry_stores():
    reset_idempotency_store()
    reset_rate_limiter()
    yield
    reset_idempotency_store()
    reset_rate_limiter()


def test_knowledge_status_endpoint() -> None:
    response = client.get("/api/knowledge/status")
    assert response.status_code == 200
    data = response.json()
    assert "chunk_count" in data
    assert "rag_backend" in data


def test_knowledge_reindex_rejects_keyword_backend() -> None:
    with patch.object(settings, "rag_backend", "keyword"):
        response = client.post("/api/knowledge/reindex", headers=AUTH_ADMIN)
    assert response.status_code == 400


def test_knowledge_reindex_requires_idempotency_key() -> None:
    response = client.post(
        "/api/knowledge/reindex",
        headers={"Authorization": "Bearer demo-admin-key"},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "bad_request"
    assert payload["message"] == "idempotency key is required"
    assert payload["detail"] == payload["message"]
    assert payload["trace_id"]


def test_admin_can_reindex_and_replay_with_same_idempotency_key() -> None:
    result = {"status": "ok", "indexed": 3}
    with (
        patch.object(settings, "rag_backend", "chroma"),
        patch("app.api.routes.knowledge.rebuild_index", return_value=result) as rebuild,
    ):
        first = client.post(
            "/api/knowledge/reindex",
            headers={
                "Authorization": "Bearer demo-admin-key",
                "Idempotency-Key": "knowledge-reindex-success",
            },
        )
        second = client.post(
            "/api/knowledge/reindex",
            headers={
                "Authorization": "Bearer demo-admin-key",
                "Idempotency-Key": "knowledge-reindex-success",
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json() == result
    assert rebuild.call_count == 1


def test_admin_reindex_rate_limit_returns_retry_after() -> None:
    result = {"status": "ok", "indexed": 3}
    with (
        patch.object(settings, "rag_backend", "chroma"),
        patch("app.api.routes.knowledge.rebuild_index", return_value=result),
    ):
        first = client.post(
            "/api/knowledge/reindex",
            headers={
                "Authorization": "Bearer demo-admin-key",
                "Idempotency-Key": "knowledge-reindex-rate-1",
            },
        )
        limited = client.post(
            "/api/knowledge/reindex",
            headers={
                "Authorization": "Bearer demo-admin-key",
                "Idempotency-Key": "knowledge-reindex-rate-2",
            },
        )

    assert first.status_code == 200
    assert limited.status_code == 429
    payload = limited.json()
    assert payload["error_code"] == "rate_limited"
    assert payload["trace_id"]
    assert payload["retry_after"] >= 1
    assert limited.headers["Retry-After"] == str(payload["retry_after"])
