from __future__ import annotations

import hashlib
import inspect
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.exceptions import IdempotencyBackendUnavailableError


IdempotencyBeginStatus = Literal["first_seen", "replay", "conflict", "in_progress"]
IdempotencyRecordStatus = Literal["in_progress", "completed"]

_SAFE_COMPONENT_RE = re.compile(r"[^a-z0-9_.-]+")
_SAFE_PREFIX_RE = re.compile(r"[^A-Za-z0-9:_.-]+")

_BEGIN_SCRIPT = """
-- IDEMPOTENCY_BEGIN_V1
redis.replicate_commands()
local current = redis.call("GET", KEYS[1])
if not current then
    local redis_time = redis.call("TIME")
    local created_at = tonumber(redis_time[1]) + tonumber(redis_time[2]) / 1000000
    local ttl_seconds = tonumber(ARGV[3])
    local record = {
        request_hash = ARGV[1],
        reservation_id = ARGV[2],
        status = "in_progress",
        response_snapshot = cjson.null,
        created_at = created_at,
        expires_at = created_at + ttl_seconds
    }
    local encoded = cjson.encode(record)
    redis.call("SET", KEYS[1], encoded, "EX", ttl_seconds)
    return {"first_seen", encoded}
end

local record = cjson.decode(current)
if record.request_hash ~= ARGV[1] then
    return {"conflict", current}
end
if record.status == "completed" then
    return {"replay", current}
end
return {"in_progress", current}
"""

_COMPLETE_SCRIPT = """
-- IDEMPOTENCY_COMPLETE_V1
local current = redis.call("GET", KEYS[1])
if not current then
    return {"missing", ""}
end

local record = cjson.decode(current)
if record.request_hash ~= ARGV[1] or record.reservation_id ~= ARGV[2] then
    return {"conflict", current}
end
if record.status == "completed" then
    return {"completed", current}
end

local ttl_milliseconds = redis.call("PTTL", KEYS[1])
if ttl_milliseconds <= 0 then
    return {"missing", ""}
end
record.status = "completed"
record.response_snapshot = cjson.decode(ARGV[3])
local encoded = cjson.encode(record)
redis.call("SET", KEYS[1], encoded, "PX", ttl_milliseconds)
return {"completed", encoded}
"""

_FORGET_SCRIPT = """
-- IDEMPOTENCY_FORGET_V1
local current = redis.call("GET", KEYS[1])
if not current then
    return 0
end
local record = cjson.decode(current)
if record.request_hash ~= ARGV[1] or record.reservation_id ~= ARGV[2] then
    return 0
end
return redis.call("DEL", KEYS[1])
"""


@dataclass(frozen=True)
class IdempotencyScope:
    tenant_id: str
    principal_id: str
    scenario: str
    capability: str
    idempotency_key: str


@dataclass
class IdempotencyRecord:
    key: str
    request_hash: str
    reservation_id: str
    status: IdempotencyRecordStatus
    response_snapshot: Any | None
    created_at: float
    expires_at: float

    @property
    def result(self) -> Any | None:
        """Compatibility accessor for the former in-memory record."""

        return self.response_snapshot


class IdempotencyStoreProtocol(Protocol):
    async def begin(
        self,
        scope: IdempotencyScope,
        request_hash: str,
    ) -> tuple[IdempotencyBeginStatus, IdempotencyRecord]: ...

    async def complete(
        self,
        scope: IdempotencyScope,
        request_hash: str,
        reservation_id: str,
        response_snapshot: Any,
    ) -> IdempotencyRecord: ...

    async def forget(
        self,
        scope: IdempotencyScope,
        request_hash: str,
        reservation_id: str,
    ) -> None: ...

    async def aclose(self) -> None: ...


class InMemoryIdempotencyStore:
    """Thread-safe local store for tests and single-process demonstrations."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 86400,
        key_prefix: str = "customer_hand:idempotency:v1",
        time_fn: Any = time.time,
    ) -> None:
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.key_prefix = key_prefix
        self._time_fn = time_fn
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    async def begin(
        self,
        scope: IdempotencyScope,
        request_hash: str,
    ) -> tuple[IdempotencyBeginStatus, IdempotencyRecord]:
        now = float(self._time_fn())
        key = build_storage_key(scope, prefix=self.key_prefix)
        with self._lock:
            record = self._records.get(key)
            if record is not None and record.expires_at <= now:
                self._records.pop(key, None)
                record = None

            if record is None:
                record = IdempotencyRecord(
                    key=key,
                    request_hash=request_hash,
                    reservation_id=uuid4().hex,
                    status="in_progress",
                    response_snapshot=None,
                    created_at=now,
                    expires_at=now + self.ttl_seconds,
                )
                self._records[key] = record
                return "first_seen", record

            if record.request_hash != request_hash:
                return "conflict", record
            if record.status == "completed":
                return "replay", record
            return "in_progress", record

    async def complete(
        self,
        scope: IdempotencyScope,
        request_hash: str,
        reservation_id: str,
        response_snapshot: Any,
    ) -> IdempotencyRecord:
        now = float(self._time_fn())
        key = build_storage_key(scope, prefix=self.key_prefix)
        with self._lock:
            record = self._records.get(key)
            if record is None or record.expires_at <= now:
                raise IdempotencyBackendUnavailableError(
                    "idempotency reservation expired before completion"
                )
            if record.request_hash != request_hash:
                raise IdempotencyBackendUnavailableError(
                    "idempotency reservation changed before completion"
                )
            if record.reservation_id != reservation_id:
                raise IdempotencyBackendUnavailableError(
                    "idempotency reservation changed before completion"
                )
            if record.status == "completed":
                return record
            completed = IdempotencyRecord(
                key=key,
                request_hash=request_hash,
                reservation_id=record.reservation_id,
                status="completed",
                response_snapshot=response_snapshot,
                created_at=record.created_at,
                expires_at=record.expires_at,
            )
            self._records[key] = completed
            return completed

    async def forget(
        self,
        scope: IdempotencyScope,
        request_hash: str,
        reservation_id: str,
    ) -> None:
        key = build_storage_key(scope, prefix=self.key_prefix)
        with self._lock:
            record = self._records.get(key)
            if (
                record is not None
                and record.request_hash == request_hash
                and record.reservation_id == reservation_id
            ):
                self._records.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    async def aclose(self) -> None:
        return None


class RedisIdempotencyStore:
    """Shared Redis store using Lua scripts for atomic state transitions."""

    def __init__(
        self,
        redis_url: str,
        *,
        ttl_seconds: int = 86400,
        key_prefix: str = "customer_hand:idempotency:v1",
        client: Any | None = None,
    ) -> None:
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.key_prefix = key_prefix
        self._client = client or Redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self._closed = False

    async def begin(
        self,
        scope: IdempotencyScope,
        request_hash: str,
    ) -> tuple[IdempotencyBeginStatus, IdempotencyRecord]:
        key = build_storage_key(scope, prefix=self.key_prefix)
        reservation_id = uuid4().hex
        try:
            raw = await self._client.eval(
                _BEGIN_SCRIPT,
                1,
                key,
                request_hash,
                reservation_id,
                str(self.ttl_seconds),
            )
            status, encoded = _script_pair(raw)
            return _begin_status(status), _record_from_json(key, encoded)
        except IdempotencyBackendUnavailableError:
            raise
        except (RedisError, OSError, TimeoutError, ValueError, TypeError) as exc:
            raise _backend_unavailable() from exc

    async def complete(
        self,
        scope: IdempotencyScope,
        request_hash: str,
        reservation_id: str,
        response_snapshot: Any,
    ) -> IdempotencyRecord:
        key = build_storage_key(scope, prefix=self.key_prefix)
        encoded_snapshot = json.dumps(
            response_snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            raw = await self._client.eval(
                _COMPLETE_SCRIPT,
                1,
                key,
                request_hash,
                reservation_id,
                encoded_snapshot,
            )
            status, encoded = _script_pair(raw)
            if status == "missing":
                raise IdempotencyBackendUnavailableError(
                    "idempotency reservation expired before completion"
                )
            if status == "conflict":
                raise IdempotencyBackendUnavailableError(
                    "idempotency reservation changed before completion"
                )
            return _record_from_json(key, encoded)
        except IdempotencyBackendUnavailableError:
            raise
        except (RedisError, OSError, TimeoutError, ValueError, TypeError) as exc:
            raise _backend_unavailable() from exc

    async def forget(
        self,
        scope: IdempotencyScope,
        request_hash: str,
        reservation_id: str,
    ) -> None:
        key = build_storage_key(scope, prefix=self.key_prefix)
        try:
            await self._client.eval(
                _FORGET_SCRIPT,
                1,
                key,
                request_hash,
                reservation_id,
            )
        except (RedisError, OSError, TimeoutError, ValueError, TypeError) as exc:
            raise _backend_unavailable() from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        closer = getattr(self._client, "aclose", None)
        if closer is None:
            closer = getattr(self._client, "close", None)
        if closer is None:
            return
        try:
            result = closer()
            if inspect.isawaitable(result):
                await result
        except (RedisError, OSError, TimeoutError):
            # Shutdown is best-effort and must remain safe when Redis is already unavailable.
            return


# Backward-compatible name used by existing tests and local callers.
IdempotencyStore = InMemoryIdempotencyStore


def build_storage_key(
    scope: IdempotencyScope,
    *,
    prefix: str = "customer_hand:idempotency:v1",
) -> str:
    safe_prefix = _SAFE_PREFIX_RE.sub("_", str(prefix or "").strip())[:100].strip(":._-")
    safe_prefix = safe_prefix or "customer_hand:idempotency:v1"
    scenario = normalize_key_component(scope.scenario, fallback="unknown_scenario")
    capability = normalize_key_component(scope.capability, fallback="unknown_capability")
    return ":".join(
        (
            safe_prefix,
            _hash_component(scope.tenant_id),
            _hash_component(scope.principal_id),
            scenario,
            capability,
            _hash_component(scope.idempotency_key),
        )
    )


def normalize_key_component(value: Any, *, fallback: str) -> str:
    raw = str(value or "").strip().lower()
    normalized = _SAFE_COMPONENT_RE.sub("_", raw).strip("_.-")
    if not normalized:
        return fallback
    normalized = normalized[:64]
    if normalized != raw:
        suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
        normalized = f"{normalized[:55]}-{suffix}"
    return normalized


def _hash_component(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _record_from_json(key: str, encoded: Any) -> IdempotencyRecord:
    data = json.loads(str(encoded))
    status = str(data.get("status") or "")
    if status not in {"in_progress", "completed"}:
        raise ValueError("invalid idempotency record status")
    return IdempotencyRecord(
        key=key,
        request_hash=str(data.get("request_hash") or ""),
        reservation_id=str(data.get("reservation_id") or ""),
        status=status,  # type: ignore[arg-type]
        response_snapshot=data.get("response_snapshot"),
        created_at=float(data.get("created_at")),
        expires_at=float(data.get("expires_at")),
    )


def _script_pair(raw: Any) -> tuple[str, str]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        raise ValueError("invalid Redis idempotency script response")
    return str(raw[0]), str(raw[1])


def _begin_status(value: str) -> IdempotencyBeginStatus:
    if value not in {"first_seen", "replay", "conflict", "in_progress"}:
        raise ValueError("invalid Redis idempotency begin status")
    return value  # type: ignore[return-value]


def _backend_unavailable() -> IdempotencyBackendUnavailableError:
    return IdempotencyBackendUnavailableError("idempotency backend is unavailable")
