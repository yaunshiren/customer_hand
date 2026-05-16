from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

T = TypeVar("T")
_tls = threading.local()


def new_trace_id() -> str:
    return uuid.uuid4().hex


def get_trace_id() -> str | None:
    tid = getattr(_tls, "trace_id", None)
    if tid is None:
        return None
    s = str(tid).strip()
    return s or None


def trace_id_from_request(request: Request) -> str:
    tid = getattr(request.state, "trace_id", None)
    if isinstance(tid, str) and tid.strip():
        return tid.strip()
    return new_trace_id()


@contextmanager
def trace_scope(trace_id: str) -> Iterator[str]:
    prev = getattr(_tls, "trace_id", None)
    _tls.trace_id = trace_id
    try:
        yield trace_id
    finally:
        if prev is None:
            if hasattr(_tls, "trace_id"):
                delattr(_tls, "trace_id")
        else:
            _tls.trace_id = prev


async def run_with_trace(request: Request, fn: Callable[[], T]) -> T:
    """在线程池执行阻塞逻辑时，在工作线程内绑定 trace_id（供日志 / telemetry）。"""

    tid = trace_id_from_request(request)

    def wrapper() -> T:
        with trace_scope(tid):
            return fn()

    return await run_in_threadpool(wrapper)
