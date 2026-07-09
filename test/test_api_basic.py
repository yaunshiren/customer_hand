from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ["LLM_ENABLED"] = "false"

from main import app  # noqa: E402
from app.entry.idempotency import reset_idempotency_store  # noqa: E402
from app.entry.rate_limit import reset_rate_limiter  # noqa: E402


client = TestClient(app)
AUTH_USER = {"Authorization": "Bearer demo-user-key"}


class FakeAgent:
    def __init__(self, tracker_store: Any) -> None:
        self.tracker_store = tracker_store

    def handle_task(self, task) -> list[dict[str, object]]:
        tracker = self.tracker_store.get_or_create(task.sender_id)
        tracker.update_with_user_message(task.normalized_text)
        tracker.add_bot_message("ok")
        return [{"recipient_id": task.sender_id, "text": "ok", "metadata": {"route": "test"}}]


class NoopTraceRecorder:
    def record_message_start(self, **kwargs: Any) -> None:
        return None

    def record_message_success(self, **kwargs: Any) -> None:
        return None

    def record_message_error(self, **kwargs: Any) -> None:
        return None


@pytest.fixture(autouse=True)
def fake_runtime():
    original_agent = app.state.agent
    original_trace_recorder = app.state.trace_recorder
    reset_rate_limiter()
    reset_idempotency_store()
    app.state.agent = FakeAgent(original_agent.tracker_store)
    app.state.trace_recorder = NoopTraceRecorder()
    try:
        yield
    finally:
        app.state.agent = original_agent
        app.state.trace_recorder = original_trace_recorder
        reset_rate_limiter()
        reset_idempotency_store()


def test_health_ok():
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "service" in data
    assert "version" in data


def test_send_message_returns_list():
    sender_id = "test_user_day4_message"

    response = client.post(
        "/api/messages",
        headers=AUTH_USER,
        json={
            "sender_id": sender_id,
            "message": "我要退货",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    first_message = data[0]
    assert "recipient_id" in first_message
    assert "text" in first_message
    assert "timestamp" in first_message
    assert "metadata" in first_message
    assert first_message["recipient_id"] == sender_id


def test_reset_tracker():
    sender_id = "user_001"

    create_response = client.post(
        "/api/messages",
        headers=AUTH_USER,
        json={
            "sender_id": sender_id,
            "message": "查物流",
        },
    )
    assert create_response.status_code == 200

    tracker_response = client.get(f"/api/tracker/{sender_id}/full")
    assert tracker_response.status_code == 200
    tracker_data = tracker_response.json()
    assert tracker_data["sender_id"] == sender_id
    assert tracker_data["exists"] is True
    assert "tracker" in tracker_data

    reset_response = client.post(f"/api/tracker/{sender_id}/reset", headers=AUTH_USER)
    assert reset_response.status_code == 200
    reset_data = reset_response.json()
    assert reset_data["sender_id"] == sender_id
    assert reset_data["reset"] is True
    assert "message" in reset_data

    after_reset_response = client.get(f"/api/tracker/{sender_id}/full")
    assert after_reset_response.status_code == 404
