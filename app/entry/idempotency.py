from __future__ import annotations

import hashlib
import inspect
import json
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from fastapi import Request

from app.core.exceptions import BadRequestError, ConflictError
from app.entry.models import EntryTask


T = TypeVar("T")
IdempotencyBeginStatus = Literal["started", "replay", "in_progress", "conflict"]

REQUIRED_IDEMPOTENCY_SCENARIOS = {
    "tool",
    "ticket",
    "create_ticket",
    "invoice",
    "create_invoice",
    "payment",
    "async_task",
    "job",
    "webhook",
}


@dataclass
class IdempotencyRecord:
    key: str
    request_hash: str
    status: Literal["started", "completed"]
    result: Any | None
    created_at: float
    updated_at: float


class IdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def begin(self, key: str, request_hash: str) -> tuple[IdempotencyBeginStatus, IdempotencyRecord]:
        now = time.time()
        with self._lock:
            record = self._records.get(key)
            if record is None:
                record = IdempotencyRecord(
                    key=key,
                    request_hash=request_hash,
                    status="started",
                    result=None,
                    created_at=now,
                    updated_at=now,
                )
                self._records[key] = record
                return "started", record

            if record.request_hash != request_hash:
                return "conflict", record
            if record.status == "completed":
                return "replay", record
            return "in_progress", record

    def complete(self, key: str, request_hash: str, result: Any) -> None:
        now = time.time()
        with self._lock:
            existing = self._records.get(key)
            self._records[key] = IdempotencyRecord(
                key=key,
                request_hash=request_hash,
                status="completed",
                result=result,
                created_at=existing.created_at if existing is not None else now,
                updated_at=now,
            )

    def forget(self, key: str) -> None:
        with self._lock:
            self._records.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()


_default_store = IdempotencyStore()


async def run_with_idempotency(
    task: EntryTask,
    request: Request,
    handler: Callable[[], Awaitable[T] | T],
    *,
    store: IdempotencyStore | None = None,
) -> T:
    key = task.idempotency_key
    if not key:
        if requires_idempotency(task):
            raise BadRequestError(
                "idempotency key is required",
                details={"scenario": task.scenario, "capability": task.capability},
            )
        return await _maybe_await(handler())

    request_hash = request_hash_for_task(task, request)
    active_store = store or _default_store
    status, record = active_store.begin(key, request_hash)

    if status == "replay":
        return record.result  # type: ignore[return-value]
    if status == "conflict":
        raise ConflictError(
            "idempotency key conflict",
            details={
                "idempotency_key": key,
                "existing_request_hash": record.request_hash,
                "request_hash": request_hash,
            },
        )
    if status == "in_progress":
        raise ConflictError(
            "idempotent request is already in progress",
            details={"idempotency_key": key, "request_hash": request_hash},
        )

    try:
        result = await _maybe_await(handler())
    except Exception:
        active_store.forget(key)
        raise

    active_store.complete(key, request_hash, result)
    return result


def request_hash_for_task(task: EntryTask, request: Request) -> str:
    body = {
        "method": request.method.upper(),
        "path": request.url.path,
        "tenant_id": task.principal.tenant_id,
        "user_id": task.principal.user_id,
        "source": task.source,
        "scenario": task.scenario,
        "capability": task.capability,
        "sender_id": task.sender_id,
        "conversation_id": task.conversation_id,
        "normalized_text": task.normalized_text,
        "metadata": _stable_metadata(task.metadata),
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def requires_idempotency(task: EntryTask) -> bool:
    scenario = str(task.scenario or "").strip().lower()
    if task.source in {"webhook", "scheduler"}:
        return True
    if scenario in REQUIRED_IDEMPOTENCY_SCENARIOS:
        return True
    return task.capability == "tool"


def reset_idempotency_store() -> None:
    _default_store.reset()


async def _maybe_await(value: Awaitable[T] | T) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


def _stable_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    ignored_keys = {"idempotency_key"}
    return {str(key): value for key, value in metadata.items() if str(key) not in ignored_keys}
