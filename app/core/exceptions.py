from __future__ import annotations

from typing import Any


class AppError(Exception):
    """应用层可预期异常基类，由全局处理器映射为 HTTP JSON。"""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code
        self.details: dict[str, Any] = dict(details or {})


class BadRequestError(AppError):
    status_code = 400
    error_code = "bad_request"


class ConflictError(AppError):
    status_code = 409
    error_code = "conflict"


class NotFoundError(AppError):
    status_code = 404
    error_code = "not_found"


class LLMServiceError(AppError):
    status_code = 502
    error_code = "llm_service_error"


class RAGServiceError(AppError):
    status_code = 502
    error_code = "rag_service_error"


class InternalError(AppError):
    status_code = 500
    error_code = "internal_error"


class UnauthorizedError(AppError):
    status_code = 401
    error_code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    error_code = "forbidden"


class RateLimitError(AppError):
    status_code = 429
    error_code = "rate_limited"


class IdempotencyBackendUnavailableError(AppError):
    status_code = 503
    error_code = "idempotency_backend_unavailable"


class RateLimitBackendUnavailableError(AppError):
    status_code = 503
    error_code = "rate_limit_backend_unavailable"
