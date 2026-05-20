from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ["LLM_ENABLED"] = "false"

from main import app  # noqa: E402

client = TestClient(app)


def test_knowledge_status_endpoint() -> None:
    response = client.get("/api/knowledge/status")
    assert response.status_code == 200
    data = response.json()
    assert "chunk_count" in data
    assert "rag_backend" in data


def test_knowledge_reindex_rejects_keyword_backend() -> None:
    from app.settings import settings  # noqa: E402

    with patch.object(settings, "rag_backend", "keyword"):
        response = client.post("/api/knowledge/reindex")
    assert response.status_code == 400
