from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

from app.entry.security import redact_text
from app.settings import settings


_DROP_KEYS = {
    "authorization",
    "api_key",
    "x_api_key",
    "token",
    "access_token",
    "secret",
    "headers",
}
_HASH_KEYS = {
    "user_id",
    "sender_id",
    "principal_id",
    "tenant_id",
    "ticket_id",
    "ticket_no",
}
_TEXT_KEYS = {
    "description",
    "raw_text",
    "normalized_text",
    "message",
    "text",
    "summary",
    "suggestion",
    "prompt",
    "context",
}


def mask_trace_payload(value: Any, *, secrets: Iterable[str] = ()) -> Any:
    configured_secrets = tuple(
        dict.fromkeys(
            str(secret)
            for secret in (*settings.api_key_principals.keys(), *secrets)
            if str(secret)
        )
    )
    return _mask(value, secrets=configured_secrets)


def _mask(value: Any, *, secrets: tuple[str, ...], field_name: str = "") -> Any:
    normalized_name = _normalized_field_name(field_name)
    if normalized_name in _DROP_KEYS:
        return "<redacted>"
    if normalized_name in _HASH_KEYS and value is not None:
        return {"sha256": _sha256(value), "redacted": True}
    if normalized_name in _TEXT_KEYS and value is not None:
        return {"sha256": _sha256(value), "redacted": True}

    if isinstance(value, dict):
        return {
            str(key): _mask(item, secrets=secrets, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_mask(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        text = value
        for secret in secrets:
            text = text.replace(secret, "<redacted-secret>")
        return redact_text(text)
    return value


def _sha256(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _normalized_field_name(value: Any) -> str:
    raw = str(value or "").strip()
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    return re.sub(r"[^a-z0-9]+", "_", camel_split.lower()).strip("_")
