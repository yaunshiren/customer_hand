from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ForbiddenError
from app.core.tracker import DialogueStateTracker
from app.core.tracker_store import InMemoryTrackerStore
from app.entry.authorization import AuthorizedContext
from app.entry.idempotency import reset_idempotency_store
from app.entry.models import EntryTask, Principal
from app.entry.rate_limit import reset_rate_limiter
from app.settings import settings
from main import app


AUTH_A_SHARED = {"Authorization": "Bearer tenant-a-shared-key"}
AUTH_B_SHARED = {"Authorization": "Bearer tenant-b-shared-key"}
AUTH_A_TARGET = {"Authorization": "Bearer tenant-a-target-key"}
AUTH_B_TARGET = {"Authorization": "Bearer tenant-b-target-key"}
AUTH_A_ADMIN = {"Authorization": "Bearer tenant-a-admin-key"}
AUTH_B_ADMIN = {"Authorization": "Bearer tenant-b-admin-key"}
AUTH_A_SHARED_ADMIN = {"Authorization": "Bearer tenant-a-shared-admin-key"}
AUTH_B_SHARED_ADMIN = {"Authorization": "Bearer tenant-b-shared-admin-key"}


def _context(
    user_id: str,
    tenant_id: str,
    *,
    roles: list[str] | None = None,
) -> AuthorizedContext:
    return AuthorizedContext.from_principal(
        Principal(
            principal_id=user_id,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles or ["user"],
            source="test_setup",
            auth_type="system",
        )
    )


class TenantAwareFakeAgent:
    def __init__(self, tracker_store: InMemoryTrackerStore) -> None:
        self.tracker_store = tracker_store
        self.tasks: list[EntryTask] = []

    def handle_task(self, task: EntryTask) -> list[dict[str, object]]:
        authorization = AuthorizedContext.from_principal(task.principal)
        tracker = self.tracker_store.get_or_create(authorization)
        tracker.update_with_user_message(task.normalized_text)
        self.tracker_store.save(authorization, tracker)
        self.tasks.append(task)
        return [
            {
                "recipient_id": task.sender_id,
                "text": "ok",
                "metadata": {"route": "tenant_authorization_test"},
            }
        ]


class NoopTraceRecorder:
    def record_message_start(self, **kwargs: Any) -> None:
        return None

    def record_message_success(self, **kwargs: Any) -> None:
        return None

    def record_message_error(self, **kwargs: Any) -> None:
        return None


@pytest.fixture()
def tenant_runtime(monkeypatch: pytest.MonkeyPatch):
    store = InMemoryTrackerStore()
    agent = TenantAwareFakeAgent(store)
    monkeypatch.setattr(app.state, "tracker_store", store)
    monkeypatch.setattr(app.state, "agent", agent)
    monkeypatch.setattr(app.state, "trace_recorder", NoopTraceRecorder())
    # Exercise the tenant-aware runtime under duplicate-ID conditions even
    # though startup validation keeps rejecting such production configuration
    # until the remaining sender-keyed stores are migrated.
    monkeypatch.setattr(
        settings,
        "api_key_principals",
        {
            "tenant-a-shared-key": {
                "principal_id": "shared_user",
                "tenant_id": "tenant_a",
                "roles": ["user"],
            },
            "tenant-b-shared-key": {
                "principal_id": "shared_user",
                "tenant_id": "tenant_b",
                "roles": ["user"],
            },
            "tenant-a-target-key": {
                "principal_id": "target_a",
                "tenant_id": "tenant_a",
                "roles": ["user"],
            },
            "tenant-b-target-key": {
                "principal_id": "target_b",
                "tenant_id": "tenant_b",
                "roles": ["user"],
            },
            "tenant-a-admin-key": {
                "principal_id": "admin_a",
                "tenant_id": "tenant_a",
                "roles": ["admin"],
            },
            "tenant-b-admin-key": {
                "principal_id": "admin_b",
                "tenant_id": "tenant_b",
                "roles": ["admin"],
            },
            "tenant-a-shared-admin-key": {
                "principal_id": "shared_admin",
                "tenant_id": "tenant_a",
                "roles": ["admin"],
            },
            "tenant-b-shared-admin-key": {
                "principal_id": "shared_admin",
                "tenant_id": "tenant_b",
                "roles": ["admin"],
            },
        },
    )
    monkeypatch.setattr(settings, "app_env", "development")
    reset_rate_limiter()
    reset_idempotency_store()
    try:
        yield store, agent
    finally:
        reset_rate_limiter()
        reset_idempotency_store()


def _seed(
    store: InMemoryTrackerStore,
    user_id: str,
    tenant_id: str,
    *,
    flow_status: str = "idle",
    message: str | None = None,
) -> DialogueStateTracker:
    authorization = _context(user_id, tenant_id)
    tracker = store.get_or_create(authorization)
    tracker.flow_status = flow_status
    if message:
        tracker.update_with_user_message(message)
    store.save(authorization, tracker)
    return tracker


def _stable_error(response) -> dict[str, object]:
    payload = response.json()
    return {
        "status_code": response.status_code,
        "error_code": payload.get("error_code"),
        "message": payload.get("message"),
        "detail": payload.get("detail"),
    }


def test_same_user_and_sender_ids_are_isolated_by_principal_tenant(
    tenant_runtime,
) -> None:
    store, _ = tenant_runtime
    _seed(store, "shared_user", "tenant_a", flow_status="tenant-a-flow")
    _seed(store, "shared_user", "tenant_b", flow_status="tenant-b-flow")
    client = TestClient(app)

    tenant_a = client.get("/api/tracker/shared_user/full", headers=AUTH_A_SHARED)
    tenant_b = client.get("/api/tracker/shared_user/full", headers=AUTH_B_SHARED)

    assert tenant_a.status_code == tenant_b.status_code == 200
    assert tenant_a.json()["tracker"]["flow_status"] == "tenant-a-flow"
    assert tenant_b.json()["tracker"]["flow_status"] == "tenant-b-flow"
    assert set(store._data) == {
        ("tenant_a", "shared_user"),
        ("tenant_b", "shared_user"),
    }


def test_user_cannot_read_another_owner_or_cross_tenant_resource(
    tenant_runtime,
) -> None:
    store, _ = tenant_runtime
    _seed(store, "target_b", "tenant_b", message="tenant B private text")
    client = TestClient(app)

    existing = client.get(
        "/api/tracker/target_b/full",
        headers={**AUTH_A_SHARED, "X-Trace-Id": "trace-cross-existing"},
    )
    missing = client.get(
        "/api/tracker/missing/full",
        headers={**AUTH_A_SHARED, "X-Trace-Id": "trace-cross-missing"},
    )

    expected = {
        "status_code": 403,
        "error_code": "forbidden",
        "message": "permission denied",
        "detail": "permission denied",
    }
    assert _stable_error(existing) == _stable_error(missing) == expected
    assert existing.json()["trace_id"] == "trace-cross-existing"
    assert missing.json()["trace_id"] == "trace-cross-missing"
    assert "tenant B private text" not in existing.text


def test_tenant_admin_accesses_same_tenant_but_not_cross_tenant(
    tenant_runtime,
) -> None:
    store, _ = tenant_runtime
    _seed(store, "target_a", "tenant_a", message="tenant A private text")
    _seed(store, "target_b", "tenant_b", message="tenant B private text")
    client = TestClient(app)

    same_tenant = client.get("/api/tracker/target_a/full", headers=AUTH_A_ADMIN)
    cross_tenant = client.get(
        "/api/tracker/target_b/full",
        headers={**AUTH_A_ADMIN, "X-Trace-Id": "trace-admin-cross"},
    )
    missing = client.get(
        "/api/tracker/missing/full",
        headers={**AUTH_A_ADMIN, "X-Trace-Id": "trace-admin-missing"},
    )

    assert same_tenant.status_code == 200
    assert set(same_tenant.json()["tracker"]) == {"flow_status", "updated_at"}
    assert _stable_error(cross_tenant) == _stable_error(missing) == {
        "status_code": 404,
        "error_code": "not_found",
        "message": "tracker not found",
        "detail": "tracker not found",
    }
    assert cross_tenant.json()["trace_id"] == "trace-admin-cross"
    assert missing.json()["trace_id"] == "trace-admin-missing"
    assert "tenant B private text" not in cross_tenant.text


def test_same_admin_principal_id_is_isolated_across_tenants(
    tenant_runtime,
) -> None:
    store, _ = tenant_runtime
    _seed(store, "shared_admin", "tenant_a", flow_status="admin-a-flow")
    _seed(store, "shared_admin", "tenant_b", flow_status="admin-b-flow")
    client = TestClient(app)

    tenant_a = client.get(
        "/api/tracker/shared_admin/full",
        headers=AUTH_A_SHARED_ADMIN,
    )
    tenant_b = client.get(
        "/api/tracker/shared_admin/full",
        headers=AUTH_B_SHARED_ADMIN,
    )

    assert tenant_a.status_code == tenant_b.status_code == 200
    assert tenant_a.json()["tracker"]["flow_status"] == "admin-a-flow"
    assert tenant_b.json()["tracker"]["flow_status"] == "admin-b-flow"
    assert tenant_a.json()["tracker"]["tenant_id"] == "tenant_a"
    assert tenant_b.json()["tracker"]["tenant_id"] == "tenant_b"


def test_reset_uses_same_tenant_boundary_and_hides_cross_tenant_existence(
    tenant_runtime,
) -> None:
    store, _ = tenant_runtime
    _seed(store, "target_a", "tenant_a")
    _seed(store, "target_b", "tenant_b")
    client = TestClient(app)

    same_tenant = client.post("/api/tracker/target_a/reset", headers=AUTH_A_ADMIN)
    cross_tenant = client.post("/api/tracker/target_b/reset", headers=AUTH_A_ADMIN)
    missing = client.post("/api/tracker/missing/reset", headers=AUTH_A_ADMIN)

    assert same_tenant.status_code == 200
    assert same_tenant.json()["reset"] is True
    assert _stable_error(cross_tenant) == _stable_error(missing) == {
        "status_code": 404,
        "error_code": "not_found",
        "message": "tracker not found",
        "detail": "tracker not found",
    }
    assert store.retrieve(_context("target_a", "tenant_a")) is None
    assert store.retrieve(_context("target_b", "tenant_b")) is not None


def test_client_tenant_role_owner_and_scope_fields_cannot_change_scope(
    tenant_runtime,
) -> None:
    store, agent = tenant_runtime
    client = TestClient(app)

    response = client.post(
        "/api/messages?tenant_id=tenant_b&owner_id=target_b&role=admin",
        headers={
            **AUTH_A_SHARED,
            "X-Tenant-Id": "tenant_b",
            "X-Role": "admin",
        },
        json={
            "message": "tenant A message",
            "tenant_id": "tenant_b",
            "owner_id": "target_b",
            "role": "admin",
            "scope": "all",
            "metadata": {
                "tenant_id": "tenant_b",
                "owner_id": "target_b",
                "role": "admin",
                "scope": "all",
            },
        },
    )

    assert response.status_code == 200
    assert agent.tasks[0].principal.tenant_id == "tenant_a"
    tenant_a_tracker = store.retrieve(_context("shared_user", "tenant_a"))
    assert tenant_a_tracker is not None
    assert tenant_a_tracker.latest_message == "tenant A message"
    assert store.retrieve(_context("shared_user", "tenant_b")) is None
    assert store.retrieve(_context("target_b", "tenant_b")) is None


def test_spoofed_headers_query_and_body_cannot_expand_reset_scope(
    tenant_runtime,
) -> None:
    store, _ = tenant_runtime
    _seed(store, "target_b", "tenant_b")
    client = TestClient(app)

    response = client.request(
        "POST",
        "/api/tracker/target_b/reset",
        headers={
            **AUTH_A_SHARED,
            "X-Tenant-Id": "tenant_b",
            "X-Role": "admin",
        },
        params={"tenant_id": "tenant_b", "role": "admin", "owner_id": "target_b"},
        json={"tenant_id": "tenant_b", "role": "admin", "owner_id": "target_b"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"
    assert store.retrieve(_context("target_b", "tenant_b")) is not None


def test_message_requests_create_separate_trackers_for_same_principal_id(
    tenant_runtime,
) -> None:
    store, _ = tenant_runtime
    client = TestClient(app)

    tenant_a = client.post(
        "/api/messages",
        headers=AUTH_A_SHARED,
        json={"message": "message from A"},
    )
    tenant_b = client.post(
        "/api/messages",
        headers=AUTH_B_SHARED,
        json={"message": "message from B"},
    )

    assert tenant_a.status_code == tenant_b.status_code == 200
    tracker_a = store.retrieve(_context("shared_user", "tenant_a"))
    tracker_b = store.retrieve(_context("shared_user", "tenant_b"))
    assert tracker_a is not None and tracker_b is not None
    assert tracker_a.latest_message == "message from A"
    assert tracker_b.latest_message == "message from B"
    assert tracker_a is not tracker_b


@pytest.mark.parametrize("path", ["full", "reset"])
def test_dev_token_cannot_establish_tracker_tenant_context(
    tenant_runtime,
    path: str,
) -> None:
    store, _ = tenant_runtime
    _seed(store, "shared_user", "tenant_a")
    client = TestClient(app)

    method = client.get if path == "full" else client.post
    response = method(
        f"/api/tracker/shared_user/{path}",
        headers={
            "Authorization": "Bearer dev:shared_user:tenant_a:admin",
            "X-Trace-Id": f"trace-dev-{path}",
        },
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"
    assert response.json()["trace_id"] == f"trace-dev-{path}"


def test_unknown_or_mismatched_tracker_scope_fails_closed(tenant_runtime) -> None:
    store, _ = tenant_runtime
    store._data[("tenant_a", "shared_user")] = DialogueStateTracker("shared_user")
    client = TestClient(app)

    response = client.get(
        "/api/tracker/shared_user/full",
        headers={**AUTH_A_SHARED, "X-Trace-Id": "trace-unknown-scope"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"
    assert response.json()["trace_id"] == "trace-unknown-scope"

    with pytest.raises(ForbiddenError, match="permission denied"):
        AuthorizedContext.from_principal(
            Principal(
                user_id="implicit_tenant_user",
                roles=["user"],
                source="test_setup",
                auth_type="system",
            )
        )

    with pytest.raises(ForbiddenError, match="permission denied"):
        store.retrieve(
            _context("admin_a", "tenant_a", roles=["admin"]),
            owner_user_id="",
        )


def test_legacy_sender_only_state_is_not_adopted_by_current_tenant(
    tenant_runtime,
) -> None:
    store, _ = tenant_runtime
    legacy = DialogueStateTracker("shared_user")
    legacy.update_with_user_message("legacy private state")
    store._data["shared_user"] = legacy.to_dict()

    current = store.get_or_create(_context("shared_user", "tenant_a"))

    assert current.tenant_id == "tenant_a"
    assert current.owner_user_id == "shared_user"
    assert current.events == []
    assert "shared_user" in store._data
    assert ("tenant_a", "shared_user") in store._data


def test_sender_only_store_methods_fail_closed(tenant_runtime) -> None:
    store, _ = tenant_runtime

    with pytest.raises(ForbiddenError, match="permission denied"):
        store.retrieve("shared_user")  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError, match="permission denied"):
        store.get_or_create("shared_user")  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError, match="permission denied"):
        store.delete("shared_user")  # type: ignore[arg-type]
