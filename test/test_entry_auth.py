from __future__ import annotations

import pytest
from starlette.requests import Request

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.entry.auth import authenticate_request, require_any_role


def _request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/probe", "headers": raw_headers})


def test_authenticate_request_allows_development_anonymous(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")

    principal = authenticate_request(_request())

    assert principal.user_id == "anonymous"
    assert principal.auth_type == "anonymous"
    assert principal.data_scope["anonymous_dev"] is True


def test_authenticate_request_rejects_missing_token_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(UnauthorizedError):
        authenticate_request(_request())


def test_authenticate_request_parses_dev_token() -> None:
    principal = authenticate_request(
        _request({"Authorization": "Bearer dev:user_001:tenant_demo:admin,evaluator"})
    )

    assert principal.user_id == "user_001"
    assert principal.tenant_id == "tenant_demo"
    assert principal.roles == ["admin", "evaluator"]
    assert principal.auth_type == "dev_token"


def test_require_any_role_rejects_missing_role() -> None:
    principal = authenticate_request(_request({"Authorization": "Bearer dev:user_001:tenant_demo:user"}))

    with pytest.raises(ForbiddenError):
        require_any_role(principal, {"admin"})
