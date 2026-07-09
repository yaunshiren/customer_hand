from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, TypeVar

from fastapi import Request
from fastapi.encoders import jsonable_encoder

from app.core.exceptions import BadRequestError, ConflictError
from app.entry.idempotency_store import (
    IdempotencyScope,
    IdempotencyStore,
    IdempotencyStoreProtocol,
    InMemoryIdempotencyStore,
    RedisIdempotencyStore,
)
from app.entry.models import EntryTask, Principal
from app.entry.security import redact_text
from app.settings import settings


T = TypeVar("T")
SnapshotEncoder = Callable[[T], Any]
SnapshotDecoder = Callable[[Any], T]

REQUIRED_IDEMPOTENCY_SCENARIOS = {
    "tool",
    "tool_write",
    "ticket",
    "create_ticket",
    "invoice",
    "create_invoice",
    "payment",
    "async_task",
    "job",
    "webhook",
}
HIGH_RISK_CAPABILITIES = {
    "ticket",
    "invoice",
    "tool_write",
    "admin_reindex",
}

_HASH_IGNORED_KEYS = {
    "trace_id",
    "request_id",
    "created_at",
    "updated_at",
    "timestamp",
    "x_trace_id",
    "x_request_id",
    "authorization",
    "api_key",
    "x_api_key",
    "token",
    "access_token",
    "credential",
    "secret",
    "idempotency_key",
}
_SNAPSHOT_OMITTED_KEYS = {
    "authorization",
    "api_key",
    "x_api_key",
    "token",
    "access_token",
    "credential",
    "secret",
    "headers",
    "request",
    "raw_text",
    "normalized_text",
    "prompt",
    "messages",
    "context",
    "contexts",
    "retrieved_contexts",
    "memory_snapshot",
    "tool_arguments",
    "arguments",
}

_default_store: IdempotencyStoreProtocol | None = None


async def run_with_idempotency(
    task: EntryTask,
    request: Request,
    handler: Callable[[], Awaitable[T] | T],
    *,
    store: IdempotencyStoreProtocol | None = None,
    snapshot_encoder: SnapshotEncoder[T] | None = None,
    snapshot_decoder: SnapshotDecoder[T] | None = None,
) -> T:
    key = task.idempotency_key
    if not key:
        if requires_idempotency(task):
            raise BadRequestError(
                "idempotency key is required",
                details={"scenario": task.scenario, "capability": task.capability},
            )
        return await _maybe_await(handler())

    scope = IdempotencyScope(
        tenant_id=task.principal.tenant_id,
        principal_id=task.principal.principal_id,
        scenario=task.scenario,
        capability=task.capability,
        idempotency_key=key,
    )
    return await _run_idempotent(
        scope=scope,
        request_hash=request_hash_for_task(task, request),
        handler=handler,
        store=store or get_idempotency_store(),
        snapshot_encoder=snapshot_encoder,
        snapshot_decoder=snapshot_decoder,
    )


async def run_request_with_idempotency(
    request: Request,
    principal: Principal,
    capability: str,
    handler: Callable[[], Awaitable[T] | T],
    *,
    scenario: str = "admin",
    store: IdempotencyStoreProtocol | None = None,
    snapshot_encoder: SnapshotEncoder[T] | None = None,
    snapshot_decoder: SnapshotDecoder[T] | None = None,
) -> T:
    key = require_idempotency_key(request, capability=capability)
    scope = IdempotencyScope(
        tenant_id=principal.tenant_id,
        principal_id=principal.principal_id,
        scenario=scenario,
        capability=capability,
        idempotency_key=key,
    )
    return await _run_idempotent(
        scope=scope,
        request_hash=request_hash_for_capability(
            request,
            principal=principal,
            scenario=scenario,
            capability=capability,
        ),
        handler=handler,
        store=store or get_idempotency_store(),
        snapshot_encoder=snapshot_encoder,
        snapshot_decoder=snapshot_decoder,
    )


def require_idempotency_key(request: Request, *, capability: str) -> str:
    key = str(request.headers.get("idempotency-key") or "").strip()
    if key:
        return key
    raise BadRequestError(
        "idempotency key is required",
        details={"capability": capability},
    )


def request_hash_for_capability(
    request: Request,
    *,
    principal: Principal,
    scenario: str = "admin",
    capability: str,
) -> str:
    body = {
        "method": request.method.upper(),
        "path": request.url.path,
        "query": _stable_query(request),
        "tenant_id": principal.tenant_id,
        "principal_id": principal.principal_id,
        "scenario": str(scenario).strip().lower(),
        "capability": str(capability).strip().lower(),
    }
    return _stable_hash(body)


def request_hash_for_task(task: EntryTask, request: Request) -> str:
    body = {
        "method": request.method.upper(),
        "path": request.url.path,
        "tenant_id": task.principal.tenant_id,
        "principal_id": task.principal.principal_id,
        "source": task.source,
        "scenario": task.scenario,
        "capability": task.capability,
        "sender_id": task.sender_id,
        "conversation_id": task.conversation_id,
        "normalized_text": task.normalized_text,
        "metadata": _stable_metadata(task.metadata),
    }
    return _stable_hash(body)


def requires_idempotency(task: EntryTask) -> bool:
    scenario = str(task.scenario or "").strip().lower()
    capability = str(task.capability or "").strip().lower()
    if task.source in {"webhook", "scheduler"}:
        return True
    if scenario in REQUIRED_IDEMPOTENCY_SCENARIOS:
        return True
    return capability == "tool" or capability in HIGH_RISK_CAPABILITIES


def build_idempotency_store() -> IdempotencyStoreProtocol:
    if settings.idempotency_backend == "redis":
        return RedisIdempotencyStore(
            settings.redis_url,
            ttl_seconds=settings.idempotency_ttl_seconds,
            key_prefix=settings.idempotency_key_prefix,
        )
    return InMemoryIdempotencyStore(
        ttl_seconds=settings.idempotency_ttl_seconds,
        key_prefix=settings.idempotency_key_prefix,
    )


def get_idempotency_store() -> IdempotencyStoreProtocol:
    global _default_store
    if _default_store is None:
        _default_store = build_idempotency_store()
    return _default_store


def reset_idempotency_store() -> None:
    store = get_idempotency_store()
    if isinstance(store, InMemoryIdempotencyStore):
        store.reset()


async def close_idempotency_store(store: IdempotencyStoreProtocol | None = None) -> None:
    active_store = store or _default_store
    if active_store is not None:
        await active_store.aclose()


def safe_response_snapshot(value: Any, *, secrets: Iterable[str] | None = None) -> Any:
    encoded = jsonable_encoder(value)
    configured_secrets = tuple(
        dict.fromkeys(
            str(secret)
            for secret in (
                *settings.api_key_principals.keys(),
                *(secrets or ()),
            )
            if str(secret)
        )
    )
    return _sanitize_snapshot(encoded, secrets=configured_secrets)


async def _run_idempotent(
    *,
    scope: IdempotencyScope,
    request_hash: str,
    handler: Callable[[], Awaitable[T] | T],
    store: IdempotencyStoreProtocol,
    snapshot_encoder: SnapshotEncoder[T] | None,
    snapshot_decoder: SnapshotDecoder[T] | None,
) -> T:
    status, record = await store.begin(scope, request_hash)
    decode = snapshot_decoder or _identity

    if status == "replay":
        return decode(record.response_snapshot)
    if status == "conflict":
        raise ConflictError(
            "idempotency key conflicts with a different request",
            error_code="idempotency_conflict",
            details={"scenario": scope.scenario, "capability": scope.capability},
        )
    if status == "in_progress":
        raise ConflictError(
            "idempotent request is already in progress",
            error_code="idempotency_in_progress",
            details={"scenario": scope.scenario, "capability": scope.capability},
        )

    try:
        result = await _maybe_await(handler())
    except Exception:
        await store.forget(scope, request_hash, record.reservation_id)
        raise

    # Once the handler returns, a write may already be committed. Completion or
    # decoding failures must not remove the reservation and permit a duplicate.
    encode = snapshot_encoder or safe_response_snapshot
    snapshot = encode(result)
    await store.complete(scope, request_hash, record.reservation_id, snapshot)
    return decode(snapshot)


async def _maybe_await(value: Awaitable[T] | T) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _stable_query(request: Request) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for key, value in request.query_params.multi_items():
        if _is_hash_ignored_field(key):
            continue
        values.append((str(key), str(value)))
    return sorted(values)


def _stable_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_metadata(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not _is_hash_ignored_field(key)
        }
    if isinstance(value, (list, tuple)):
        return [_stable_metadata(item) for item in value]
    return value


def _sanitize_snapshot(value: Any, *, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_snapshot(item, secrets=secrets)
            for key, item in value.items()
            if _normalized_field_name(key) not in _SNAPSHOT_OMITTED_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_snapshot(item, secrets=secrets) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_snapshot(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        text = value
        for secret in secrets:
            text = text.replace(str(secret), "<redacted-secret>")
        return redact_text(text)
    return value


def _normalized_field_name(value: Any) -> str:
    raw = str(value or "").strip()
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    return re.sub(r"[^a-z0-9]+", "_", camel_split.lower()).strip("_")


def _is_hash_ignored_field(value: Any) -> bool:
    name = _normalized_field_name(value)
    return name in _HASH_IGNORED_KEYS or "timestamp" in name


def _identity(value: Any) -> Any:
    return value


__all__ = [
    "IdempotencyScope",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "RedisIdempotencyStore",
    "build_idempotency_store",
    "close_idempotency_store",
    "get_idempotency_store",
    "request_hash_for_capability",
    "request_hash_for_task",
    "requires_idempotency",
    "reset_idempotency_store",
    "run_request_with_idempotency",
    "run_with_idempotency",
    "safe_response_snapshot",
]
