from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError, RateLimitError

logger = logging.getLogger(__name__)


def _trace_from_request(request: Request) -> str:
    tid = getattr(request.state, "trace_id", None)
    if isinstance(tid, str) and tid.strip():
        return tid.strip()
    return "-"


def _error_body(
    request: Request,
    *,
    detail: str,
    error_code: str,
    message: str | None = None,
) -> dict[str, Any]:
    text = str(message or detail)
    return {
        "error_code": error_code,
        "message": text,
        "detail": str(detail),
        "trace_id": _trace_from_request(request),
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app_error code=%s status=%s msg=%s",
            exc.error_code,
            exc.status_code,
            exc.message,
        )
        payload = _error_body(
            request,
            detail=exc.message,
            error_code=exc.error_code,
        )
        if exc.details:
            payload["details"] = exc.details
        headers: dict[str, str] = {}
        if isinstance(exc, RateLimitError):
            retry_after = max(1, int(exc.details.get("retry_after_seconds") or 1))
            payload["retry_after"] = retry_after
            headers["Retry-After"] = str(retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            content=payload,
            headers=headers,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        detail = str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, detail=detail, error_code="http_error"),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            {
                "location": list(item.get("loc") or []),
                "message": str(item.get("msg") or "invalid value"),
                "type": str(item.get("type") or "validation_error"),
            }
            for item in exc.errors()
        ]
        payload = _error_body(
            request,
            detail="request validation failed",
            error_code="validation_error",
        )
        payload["details"] = {"errors": details}
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        tid = _trace_from_request(request)
        logger.exception("unhandled_exception trace_id=%s", tid, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_error_body(
                request,
                detail="服务器内部错误，请稍后重试。",
                error_code="internal_error",
            ),
        )
