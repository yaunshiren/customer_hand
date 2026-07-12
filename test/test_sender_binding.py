from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.tracker_store import InMemoryTrackerStore
from app.entry.authorization import AuthorizedContext
from app.entry.models import EntryTask, Principal
from app.entry.rate_limit_store import RateLimitDecision
from main import app


AUTH_USER = {"Authorization": "Bearer demo-user-key"}
AUTH_ADMIN = {"Authorization": "Bearer demo-admin-key"}


def _context(
    user_id: str,
    *,
    tenant_id: str = "tenant_demo",
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


class SideEffectSpyAgent:
    def __init__(self, tracker_store: InMemoryTrackerStore) -> None:
        self.tracker_store = tracker_store
        self.tasks: list[EntryTask] = []
        self.agent_calls = 0
        self.tracker_writes = 0
        self.memory_reads = 0
        self.memory_writes = 0
        self.rag_calls = 0
        self.tool_calls = 0
        self.ticket_calls = 0

    def handle_task(self, task: EntryTask) -> list[dict[str, object]]:
        self.agent_calls += 1
        self.tasks.append(task)
        self.tracker_writes += 1
        tracker = self.tracker_store.get_or_create(
            AuthorizedContext.from_principal(task.principal)
        )
        tracker.update_with_user_message(task.normalized_text)

        # These counters model the downstream components that become reachable
        # only after Agent invocation. A rejected sender must leave all at zero.
        self.memory_reads += 1
        self.memory_writes += 1
        self.rag_calls += 1
        self.tool_calls += 1
        self.ticket_calls += 1
        return [
            {
                "recipient_id": task.sender_id,
                "text": "ok",
                "metadata": {"route": "sender_binding_test"},
            }
        ]


class CapturingTraceRecorder:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.successes: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []

    def record_message_start(self, **kwargs: Any) -> None:
        self.starts.append(dict(kwargs))

    def record_message_success(self, **kwargs: Any) -> None:
        self.successes.append(dict(kwargs))

    def record_message_error(self, **kwargs: Any) -> None:
        self.errors.append(dict(kwargs))


class CountingAllowRateLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def check(self, scope, policy) -> RateLimitDecision:
        self.calls += 1
        return RateLimitDecision(
            allowed=True,
            key="sender-binding-test",
            policy=policy,
            remaining=max(0, policy.capacity - 1),
        )


@pytest.fixture()
def sender_state(monkeypatch: pytest.MonkeyPatch):
    tracker_store = InMemoryTrackerStore()
    agent = SideEffectSpyAgent(tracker_store)
    recorder = CapturingTraceRecorder()
    limiter = CountingAllowRateLimiter()
    monkeypatch.setattr(app.state, "tracker_store", tracker_store)
    monkeypatch.setattr(app.state, "agent", agent)
    monkeypatch.setattr(app.state, "trace_recorder", recorder)
    monkeypatch.setattr(app.state, "rate_limiter", limiter)
    return agent, tracker_store, recorder, limiter


def _stable_error(response) -> dict[str, Any]:
    payload = response.json()
    return {
        "status_code": response.status_code,
        "error_code": payload.get("error_code"),
        "message": payload.get("message"),
        "detail": payload.get("detail"),
    }


def _assert_no_downstream_side_effects(
    agent: SideEffectSpyAgent,
    recorder: CapturingTraceRecorder,
    limiter: CountingAllowRateLimiter,
) -> None:
    assert agent.agent_calls == 0
    assert agent.tracker_writes == 0
    assert agent.memory_reads == 0
    assert agent.memory_writes == 0
    assert agent.rag_calls == 0
    assert agent.tool_calls == 0
    assert agent.ticket_calls == 0
    assert recorder.starts == []
    assert recorder.successes == []
    assert recorder.errors == []
    assert limiter.calls == 0


def test_message_without_authentication_returns_401_before_side_effects(
    sender_state,
) -> None:
    agent, _, recorder, limiter = sender_state
    client = TestClient(app)

    response = client.post("/api/messages", json={"message": "hello"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"
    _assert_no_downstream_side_effects(agent, recorder, limiter)


def test_client_authored_dev_token_cannot_establish_message_sender(
    sender_state,
) -> None:
    agent, tracker_store, recorder, limiter = sender_state
    client = TestClient(app)

    response = client.post(
        "/api/messages",
        headers={
            "Authorization": "Bearer dev:victim:tenant_b:admin",
            "X-Trace-Id": "trace-dev-token-sender",
        },
        json={"message": "poison victim state"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"
    assert response.json()["trace_id"] == "trace-dev-token-sender"
    assert tracker_store.retrieve(
        _context("victim", tenant_id="tenant_b")
    ) is None
    _assert_no_downstream_side_effects(agent, recorder, limiter)


def test_missing_sender_uses_authenticated_principal_and_ignores_spoofed_context(
    sender_state,
) -> None:
    agent, tracker_store, recorder, limiter = sender_state
    client = TestClient(app)

    response = client.post(
        "/api/messages",
        headers={**AUTH_USER, "X-Role": "admin", "X-Tenant-Id": "tenant_b"},
        params={"sender_id": "victim", "role": "admin", "tenant_id": "tenant_b"},
        json={
            "message": "hello",
            "tenant_id": "tenant_b",
            "role": "admin",
            "owner_id": "victim",
            "scope": "all",
            "metadata": {
                "sender_id": "victim",
                "tenant_id": "tenant_b",
                "role": "admin",
                "owner_id": "victim",
                "scope": "all",
            },
        },
    )

    assert response.status_code == 200
    task = agent.tasks[0]
    assert task.sender_id == "user_001"
    assert task.conversation_id == "user_001"
    assert task.principal.user_id == "user_001"
    assert task.principal.tenant_id == "tenant_demo"
    assert task.principal.roles == ["user"]
    assert response.json()[0]["recipient_id"] == "user_001"
    assert tracker_store.retrieve(_context("user_001")) is not None
    assert tracker_store.retrieve(_context("victim")) is None
    assert recorder.starts[0]["sender_id"] == "user_001"
    assert recorder.successes[0]["sender_id"] == "user_001"
    assert limiter.calls == 1


def test_matching_sender_is_accepted(sender_state) -> None:
    agent, _, recorder, limiter = sender_state
    client = TestClient(app)

    response = client.post(
        "/api/messages",
        headers=AUTH_USER,
        json={"sender_id": "user_001", "message": "hello"},
    )

    assert response.status_code == 200
    assert agent.tasks[0].sender_id == "user_001"
    assert recorder.starts[0]["sender_id"] == "user_001"
    assert limiter.calls == 1


def test_mismatched_sender_is_403_without_any_state_side_effect_or_existence_leak(
    sender_state,
) -> None:
    agent, tracker_store, recorder, limiter = sender_state
    victim_existing_context = _context("victim_existing")
    existing = tracker_store.get_or_create(victim_existing_context)
    existing.update_with_user_message("existing private state")
    existing_snapshot = existing.to_dict()
    client = TestClient(app)

    existing_response = client.post(
        "/api/messages",
        headers={**AUTH_USER, "X-Trace-Id": "trace-sender-existing"},
        json={"sender_id": "victim_existing", "message": "poison state"},
    )
    missing_response = client.post(
        "/api/messages",
        headers={**AUTH_USER, "X-Trace-Id": "trace-sender-missing"},
        json={"sender_id": "victim_missing", "message": "poison state"},
    )

    expected = {
        "status_code": 403,
        "error_code": "forbidden",
        "message": "permission denied",
        "detail": "permission denied",
    }
    assert _stable_error(existing_response) == expected
    assert _stable_error(missing_response) == expected
    assert existing_response.json()["trace_id"] == "trace-sender-existing"
    assert missing_response.json()["trace_id"] == "trace-sender-missing"
    assert existing_response.headers["X-Trace-Id"] == "trace-sender-existing"
    assert missing_response.headers["X-Trace-Id"] == "trace-sender-missing"
    assert tracker_store.retrieve(victim_existing_context).to_dict() == existing_snapshot
    assert tracker_store.retrieve(_context("victim_missing")) is None
    _assert_no_downstream_side_effects(agent, recorder, limiter)


def test_spoofed_role_tenant_owner_scope_cannot_authorize_mismatched_sender(
    sender_state,
) -> None:
    agent, tracker_store, recorder, limiter = sender_state
    client = TestClient(app)

    response = client.post(
        "/api/messages",
        headers={
            **AUTH_USER,
            "X-Trace-Id": "trace-sender-spoof",
            "X-Role": "admin",
            "X-Tenant-Id": "tenant_b",
        },
        params={"role": "admin", "tenant_id": "tenant_b", "scope": "all"},
        json={
            "sender_id": "victim",
            "message": "create a ticket",
            "scenario": "ticket",
            "role": "admin",
            "tenant_id": "tenant_b",
            "owner_id": "victim",
            "scope": "all",
            "metadata": {
                "role": "admin",
                "tenant_id": "tenant_b",
                "owner_id": "victim",
                "scope": "all",
            },
        },
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"
    assert response.json()["trace_id"] == "trace-sender-spoof"
    assert tracker_store.retrieve(_context("victim")) is None
    _assert_no_downstream_side_effects(agent, recorder, limiter)


def test_admin_cannot_proxy_another_user_through_sender_id(sender_state) -> None:
    agent, tracker_store, recorder, limiter = sender_state
    client = TestClient(app)

    response = client.post(
        "/api/messages",
        headers={**AUTH_ADMIN, "X-Trace-Id": "trace-admin-proxy"},
        json={"sender_id": "user_001", "message": "proxy request"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"
    assert response.json()["trace_id"] == "trace-admin-proxy"
    assert tracker_store.retrieve(_context("user_001")) is None
    _assert_no_downstream_side_effects(agent, recorder, limiter)
