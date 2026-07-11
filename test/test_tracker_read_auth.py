from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.tracker_store import InMemoryTrackerStore
from app.settings import settings
from main import app


AUTH_USER = {"Authorization": "Bearer demo-user-key"}
AUTH_ADMIN = {"Authorization": "Bearer demo-admin-key"}
AUTH_TENANT_B_ADMIN = {"Authorization": "Bearer tenant-b-admin-key"}
SENSITIVE_TRACKER_FIELDS = {
    "memory",
    "slots",
    "events",
    "latest_message",
    "latest_bot_message",
    "active_flow",
    "flow_step_index",
    "slot_to_collect",
    "flow_history",
    "latest_action_name",
}


@pytest.fixture()
def tracker_store(monkeypatch: pytest.MonkeyPatch) -> InMemoryTrackerStore:
    original_store = app.state.tracker_store
    store = InMemoryTrackerStore()
    monkeypatch.setattr(app.state, "tracker_store", store)
    monkeypatch.setitem(
        settings.api_key_principals,
        "tenant-b-admin-key",
        {
            "principal_id": "admin_tenant_b",
            "tenant_id": "tenant_b",
            "roles": ["admin"],
        },
    )
    try:
        yield store
    finally:
        app.state.tracker_store = original_store


def _create_sensitive_tracker(store: InMemoryTrackerStore, sender_id: str) -> None:
    tracker = store.get_or_create(sender_id)
    tracker.update_with_user_message("private customer message")
    tracker.add_bot_message("private assistant reply")
    tracker.set_slot("order_id", "ORDER-SECRET")
    tracker.active_flow = "postsale"
    tracker.flow_history.append({"internal": "debug"})


def _stable_error(response) -> dict[str, Any]:
    payload = response.json()
    return {
        "status_code": response.status_code,
        "error_code": payload.get("error_code"),
        "message": payload.get("message"),
        "detail": payload.get("detail"),
    }


def test_tracker_full_rejects_unauthenticated_request(
    tracker_store: InMemoryTrackerStore,
) -> None:
    _create_sensitive_tracker(tracker_store, "user_001")
    client = TestClient(app)

    response = client.get("/api/tracker/user_001/full")

    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"


def test_tracker_full_owner_receives_only_minimal_status(
    tracker_store: InMemoryTrackerStore,
) -> None:
    _create_sensitive_tracker(tracker_store, "user_001")
    client = TestClient(app)

    response = client.get("/api/tracker/user_001/full", headers=AUTH_USER)

    assert response.status_code == 200
    payload = response.json()
    assert payload["sender_id"] == "user_001"
    assert payload["exists"] is True
    assert set(payload["tracker"]) == {"flow_status", "updated_at"}
    assert not SENSITIVE_TRACKER_FIELDS.intersection(payload["tracker"])
    assert "private customer message" not in response.text
    assert "ORDER-SECRET" not in response.text


def test_tracker_full_non_owner_cannot_distinguish_existing_from_missing(
    tracker_store: InMemoryTrackerStore,
) -> None:
    _create_sensitive_tracker(tracker_store, "other_user")
    client = TestClient(app)

    existing = client.get("/api/tracker/other_user/full", headers=AUTH_USER)
    missing = client.get("/api/tracker/missing_user/full", headers=AUTH_USER)

    assert _stable_error(existing) == _stable_error(missing) == {
        "status_code": 403,
        "error_code": "forbidden",
        "message": "permission denied",
        "detail": "permission denied",
    }


def test_tracker_full_ignores_client_role_tenant_and_sender_spoofing(
    tracker_store: InMemoryTrackerStore,
) -> None:
    _create_sensitive_tracker(tracker_store, "other_user")
    client = TestClient(app)

    response = client.get(
        "/api/tracker/other_user/full",
        headers={**AUTH_USER, "X-Role": "admin", "X-Tenant-Id": "tenant_b"},
        params={
            "role": "admin",
            "tenant_id": "tenant_b",
            "sender_id": "user_001",
        },
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"


def test_tracker_full_rejects_client_authored_dev_token_identity(
    tracker_store: InMemoryTrackerStore,
) -> None:
    _create_sensitive_tracker(tracker_store, "user_001")
    client = TestClient(app)

    response = client.get(
        "/api/tracker/user_001/full",
        headers={
            "Authorization": "Bearer dev:user_001:tenant_demo:admin",
        },
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"


def test_tracker_full_server_configured_admin_can_read_own_full_tracker(
    tracker_store: InMemoryTrackerStore,
) -> None:
    _create_sensitive_tracker(tracker_store, "admin_001")
    client = TestClient(app)

    response = client.get("/api/tracker/admin_001/full", headers=AUTH_ADMIN)

    assert response.status_code == 200
    tracker_payload = response.json()["tracker"]
    assert SENSITIVE_TRACKER_FIELDS.issubset(tracker_payload)
    assert tracker_payload["slots"]["order_id"] == "ORDER-SECRET"


@pytest.mark.parametrize(
    "app_env",
    ["staging", "pilot", "prod", "production", "dev", "unknown-environment"],
)
def test_tracker_full_non_local_admin_owner_receives_only_minimal_status(
    tracker_store: InMemoryTrackerStore,
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
) -> None:
    _create_sensitive_tracker(tracker_store, "admin_001")
    monkeypatch.setattr(settings, "app_env", app_env)
    client = TestClient(app)

    response = client.request(
        "GET",
        "/api/tracker/admin_001/full",
        headers={
            **AUTH_ADMIN,
            "X-Role": "admin",
            "X-Tenant-Id": "tenant_demo",
            "X-Debug-Tracker": "true",
        },
        params={"debug": "true", "full": "true", "tenant_id": "tenant_demo"},
        json={"debug": True, "full": True, "role": "admin"},
    )

    assert response.status_code == 200
    tracker_payload = response.json()["tracker"]
    assert set(tracker_payload) == {"flow_status", "updated_at"}
    assert not SENSITIVE_TRACKER_FIELDS.intersection(tracker_payload)
    assert "private customer message" not in response.text
    assert "ORDER-SECRET" not in response.text


def test_tracker_full_admin_access_to_other_owner_fails_closed_without_tenant_scope(
    tracker_store: InMemoryTrackerStore,
) -> None:
    _create_sensitive_tracker(tracker_store, "user_001")
    client = TestClient(app)

    response = client.get("/api/tracker/user_001/full", headers=AUTH_ADMIN)

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"


def test_tracker_full_tenant_a_admin_cannot_read_tenant_b_tracker(
    tracker_store: InMemoryTrackerStore,
) -> None:
    _create_sensitive_tracker(tracker_store, "admin_tenant_b")
    client = TestClient(app)

    cross_tenant = client.get(
        "/api/tracker/admin_tenant_b/full",
        headers=AUTH_ADMIN,
    )
    tenant_b_owner = client.get(
        "/api/tracker/admin_tenant_b/full",
        headers=AUTH_TENANT_B_ADMIN,
    )

    assert cross_tenant.status_code == 403
    assert tenant_b_owner.status_code == 200
    assert "memory" in tenant_b_owner.json()["tracker"]


def test_tracker_reset_authorization_behavior_is_unchanged(
    tracker_store: InMemoryTrackerStore,
) -> None:
    _create_sensitive_tracker(tracker_store, "user_001")
    _create_sensitive_tracker(tracker_store, "other_user")
    client = TestClient(app)

    owner = client.post("/api/tracker/user_001/reset", headers=AUTH_USER)
    non_owner = client.post("/api/tracker/other_user/reset", headers=AUTH_USER)
    admin = client.post("/api/tracker/other_user/reset", headers=AUTH_ADMIN)

    assert owner.status_code == 200
    assert non_owner.status_code == 403
    assert admin.status_code == 200


def test_inspect_is_dev_only_or_requires_server_configured_admin(
    tracker_store: InMemoryTrackerStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_sensitive_tracker(tracker_store, "user_001")
    client = TestClient(app)

    monkeypatch.setattr(settings, "app_env", "development")
    assert client.get("/inspect").status_code == 200
    assert client.get("/api/tracker/user_001/full").status_code == 401

    monkeypatch.setattr(settings, "app_env", "production")
    assert client.get("/inspect").status_code == 401
    assert client.get("/inspect", headers=AUTH_USER).status_code == 403
    assert client.get("/inspect", headers=AUTH_ADMIN).status_code == 200

    monkeypatch.setattr(settings, "app_env", "staging")
    dev_admin = {
        "Authorization": "Bearer dev:admin_001:tenant_demo:admin",
    }
    assert client.get("/inspect", headers=dev_admin).status_code == 403
