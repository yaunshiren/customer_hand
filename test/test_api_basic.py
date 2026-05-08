from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ["LLM_ENABLED"] = "false"

from main import app  # noqa: E402


client = TestClient(app)


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
    sender_id = "test_user_day4_reset"

    create_response = client.post(
        "/api/messages",
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

    reset_response = client.post(f"/api/tracker/{sender_id}/reset")
    assert reset_response.status_code == 200
    reset_data = reset_response.json()
    assert reset_data["sender_id"] == sender_id
    assert reset_data["reset"] is True
    assert "message" in reset_data

    after_reset_response = client.get(f"/api/tracker/{sender_id}/full")
    assert after_reset_response.status_code == 404
