from __future__ import annotations

import pytest
from starlette.requests import Request

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.entry.auth import authenticate_request, require_any_role
from app.settings import settings


def _request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/probe", "headers": raw_headers})


def test_authenticate_request_rejects_missing_api_key() -> None:
    with pytest.raises(UnauthorizedError):
        authenticate_request(_request())


def test_authenticate_request_rejects_missing_token_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")

    with pytest.raises(UnauthorizedError):
        authenticate_request(_request())


def test_authenticate_request_parses_bearer_api_key() -> None:
    principal = authenticate_request(
        _request({"Authorization": "Bearer demo-user-key"})
    )

    assert principal.principal_id == "user_001"
    assert principal.user_id == "user_001"
    assert principal.tenant_id == "tenant_demo"
    assert principal.roles == ["user"]
    assert principal.source == "authorization_bearer"
    assert principal.auth_type == "api_key"


def test_authenticate_request_parses_x_api_key() -> None:
    principal = authenticate_request(_request({"X-API-Key": "demo-evaluator-key"}))

    assert principal.principal_id == "evaluator_001"
    assert principal.roles == ["evaluator"]
    assert principal.source == "x_api_key"


def test_authorization_bearer_takes_priority_over_x_api_key() -> None:
    principal = authenticate_request(
        _request(
            {
                "Authorization": "Bearer demo-admin-key",
                "X-API-Key": "demo-user-key",
            }
        )
    )

    assert principal.principal_id == "admin_001"
    assert principal.roles == ["admin"]


def test_authenticate_request_rejects_invalid_api_key() -> None:
    with pytest.raises(UnauthorizedError):
        authenticate_request(_request({"Authorization": "Bearer not-a-valid-key"}))


def test_authenticate_request_parses_dev_token_for_compatibility() -> None:
    principal = authenticate_request(
        _request({"Authorization": "Bearer dev:user_001:tenant_demo:admin,evaluator"})
    )

    assert principal.user_id == "user_001"
    assert principal.tenant_id == "tenant_demo"
    assert principal.roles == ["admin", "evaluator"]
    assert principal.auth_type == "dev_token"
    assert principal.source == "dev_token"


def test_authenticate_request_rejects_dev_token_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_env", "production")

    with pytest.raises(UnauthorizedError):
        authenticate_request(
            _request({"Authorization": "Bearer dev:user_001:tenant_demo:user"})
        )


def test_require_any_role_rejects_missing_role() -> None:
    principal = authenticate_request(_request({"Authorization": "Bearer demo-user-key"}))

    with pytest.raises(ForbiddenError):
        require_any_role(principal, {"admin"})
