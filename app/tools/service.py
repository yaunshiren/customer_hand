from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.trace import get_trace_id
from app.persistence.tool_recorder import record_tool_trace
from app.settings import settings
from app.tickets.models import Ticket
from app.tickets.service import TicketNotFoundError, TicketService
from app.tools.mock_store import MockCustomerServiceStore, MockToolError
from app.tools.models import ToolCallResult, ToolError


@dataclass(frozen=True)
class ToolExecutionPolicy:
    timeout_seconds: float = 3.0
    max_retries: int = 1
    retry_backoff_seconds: float = 0.0


class _EmptyToolResultError(Exception):
    pass


class QueryOrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, description="Order id provided by the user.")

    @field_validator("order_id")
    @classmethod
    def _validate_order_id(cls, value: str) -> str:
        return _clean_required_text(value, "order_id")


class QueryLogisticsArgs(QueryOrderArgs):
    pass


class CreateTicketArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, description="Ticket category, such as complaint or logistics.")
    description: str = Field(min_length=1, description="Original user issue or a concise issue description.")
    user_id: str = Field(min_length=1, description="User id used to associate the ticket with a customer.")

    @field_validator("category", "description", "user_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _clean_required_text(value, info.field_name)


class QueryTicketStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_no: str = Field(min_length=1, description="User-visible ticket number.")

    @field_validator("ticket_no")
    @classmethod
    def _validate_ticket_no(cls, value: str) -> str:
        return _clean_required_text(value, "ticket_no").upper()


class CreateInvoiceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, description="Order id that needs an invoice.")
    title: str = Field(min_length=1, description="Invoice title, such as a company or personal title.")

    @field_validator("order_id", "title")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _clean_required_text(value, info.field_name)


class MockBusinessToolService:
    def __init__(
        self,
        store: MockCustomerServiceStore | None = None,
        *,
        policy: ToolExecutionPolicy | None = None,
        ticket_service: TicketService | None = None,
    ) -> None:
        self.store = store or MockCustomerServiceStore()
        self.policy = policy or ToolExecutionPolicy()
        self.ticket_service = ticket_service

    def query_order(self, order_id: str, *, trace_id: str | None = None) -> ToolCallResult:
        return self._run(
            tool_name="query_order",
            args_model=QueryOrderArgs,
            raw_arguments={"order_id": order_id},
            operation=lambda args: self.store.get_order(args.order_id),
            trace_id=trace_id,
        )

    def query_logistics(self, order_id: str, *, trace_id: str | None = None) -> ToolCallResult:
        return self._run(
            tool_name="query_logistics",
            args_model=QueryLogisticsArgs,
            raw_arguments={"order_id": order_id},
            operation=lambda args: self.store.get_logistics(args.order_id),
            trace_id=trace_id,
        )

    def create_ticket(
        self,
        category: str,
        description: str,
        user_id: str,
        *,
        trace_id: str | None = None,
    ) -> ToolCallResult:
        return self._run(
            tool_name="create_ticket",
            args_model=CreateTicketArgs,
            raw_arguments={"category": category, "description": description, "user_id": user_id},
            operation=self._create_ticket,
            trace_id=trace_id,
            max_retries_override=0,
            metadata_source=settings.ticket_store_backend,
            mock=settings.ticket_store_backend == "memory",
        )

    def query_ticket_status(
        self,
        ticket_no: str,
        *,
        trace_id: str | None = None,
    ) -> ToolCallResult:
        return self._run(
            tool_name="query_ticket_status",
            args_model=QueryTicketStatusArgs,
            raw_arguments={"ticket_no": ticket_no},
            operation=self._query_ticket_status,
            trace_id=trace_id,
            metadata_source=settings.ticket_store_backend,
            mock=settings.ticket_store_backend == "memory",
        )

    def create_invoice(self, order_id: str, title: str, *, trace_id: str | None = None) -> ToolCallResult:
        return self._run(
            tool_name="create_invoice",
            args_model=CreateInvoiceArgs,
            raw_arguments={"order_id": order_id, "title": title},
            operation=lambda args: self.store.create_invoice(order_id=args.order_id, title=args.title),
            trace_id=trace_id,
        )

    def _run(
        self,
        *,
        tool_name: str,
        args_model: type[BaseModel],
        raw_arguments: dict[str, Any],
        operation: Callable[[Any], dict[str, Any]],
        trace_id: str | None,
        max_retries_override: int | None = None,
        metadata_source: str = "mock",
        mock: bool = True,
    ) -> ToolCallResult:
        started_at = time.perf_counter()
        effective_trace_id = trace_id or get_trace_id()
        arguments = dict(raw_arguments)
        attempts: list[dict[str, Any]] = []
        effective_max_retries = (
            self.policy.max_retries
            if max_retries_override is None
            else max(0, int(max_retries_override))
        )

        try:
            parsed_args = args_model.model_validate(raw_arguments)
            arguments = parsed_args.model_dump(mode="json")
        except ValidationError as exc:
            result = self._failed_result(
                tool_name=tool_name,
                arguments=arguments,
                started_at=started_at,
                trace_id=effective_trace_id,
                error=ToolError(
                    code="TOOL_ARGUMENT_ERROR",
                    message="Tool arguments failed validation.",
                    retryable=False,
                    details={"errors": _validation_errors(exc)},
                ),
                attempts=attempts,
                max_retries=effective_max_retries,
                metadata_source=metadata_source,
                mock=mock,
            )
        else:
            result = self._execute_with_policy(
                tool_name=tool_name,
                arguments=arguments,
                parsed_args=parsed_args,
                operation=operation,
                started_at=started_at,
                trace_id=effective_trace_id,
                attempts=attempts,
                max_retries=effective_max_retries,
                metadata_source=metadata_source,
                mock=mock,
            )

        record_tool_trace(
            tool_name=tool_name,
            arguments_json=result.arguments,
            result_json=result.to_dict(),
            status=result.status,
            latency_ms=result.latency_ms,
            trace_id=effective_trace_id,
        )
        return result

    def _failed_result(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        started_at: float,
        trace_id: str | None,
        error: ToolError,
        attempts: list[dict[str, Any]] | None = None,
        max_retries: int | None = None,
        metadata_source: str = "mock",
        mock: bool = True,
    ) -> ToolCallResult:
        return ToolCallResult(
            tool_name=tool_name,
            success=False,
            status="failed",
            arguments=arguments,
            data=None,
            error=error,
            latency_ms=_elapsed_ms(started_at),
            trace_id=trace_id,
            metadata=self._metadata(
                attempts or [],
                max_retries=max_retries,
                source=metadata_source,
                mock=mock,
            ),
        )

    def _execute_with_policy(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        parsed_args: Any,
        operation: Callable[[Any], dict[str, Any]],
        started_at: float,
        trace_id: str | None,
        attempts: list[dict[str, Any]],
        max_retries: int,
        metadata_source: str,
        mock: bool,
    ) -> ToolCallResult:
        max_attempts = max(1, max_retries + 1)
        last_error: ToolError | None = None

        for attempt_index in range(1, max_attempts + 1):
            attempt_started_at = time.perf_counter()
            data: dict[str, Any] | None = None
            try:
                data = self._execute_operation(operation, parsed_args)
                if _is_empty_tool_data(data):
                    raise _EmptyToolResultError()

                attempts.append(
                    {
                        "attempt": attempt_index,
                        "status": "success",
                        "latency_ms": _elapsed_ms(attempt_started_at),
                    }
                )
                return ToolCallResult(
                    tool_name=tool_name,
                    success=True,
                    status="success",
                    arguments=arguments,
                    data=data,
                    latency_ms=_elapsed_ms(started_at),
                    trace_id=trace_id,
                    metadata=self._metadata(
                        attempts,
                        max_retries=max_retries,
                        source=metadata_source,
                        mock=mock,
                    ),
                )
            except TimeoutError:
                last_error = ToolError(
                    code="TOOL_TIMEOUT",
                    message="Tool execution timed out.",
                    retryable=attempt_index < max_attempts,
                    details={"timeout_seconds": self.policy.timeout_seconds},
                )
            except _EmptyToolResultError:
                last_error = ToolError(
                    code="TOOL_EMPTY_RESULT",
                    message="Tool returned an empty result.",
                    retryable=attempt_index < max_attempts,
                )
            except MockToolError as exc:
                last_error = ToolError(
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable and attempt_index < max_attempts,
                    details=exc.details,
                )
            except Exception as exc:
                last_error = ToolError(
                    code="TOOL_FAILURE",
                    message=str(exc) or exc.__class__.__name__,
                    retryable=attempt_index < max_attempts,
                    details={"error_type": exc.__class__.__name__},
                )

            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "failed",
                    "latency_ms": _elapsed_ms(attempt_started_at),
                    "error_code": last_error.code if last_error else "TOOL_FAILURE",
                }
            )
            if last_error is None or not last_error.retryable:
                break
            if self.policy.retry_backoff_seconds > 0:
                time.sleep(self.policy.retry_backoff_seconds)

        return self._failed_result(
            tool_name=tool_name,
            arguments=arguments,
            started_at=started_at,
            trace_id=trace_id,
            error=last_error
            or ToolError(
                code="TOOL_FAILURE",
                message="Tool execution failed.",
                retryable=False,
            ),
            attempts=attempts,
            max_retries=max_retries,
            metadata_source=metadata_source,
            mock=mock,
        )

    def _execute_operation(self, operation: Callable[[Any], dict[str, Any]], parsed_args: Any) -> dict[str, Any]:
        timeout_seconds = max(0.001, float(self.policy.timeout_seconds))
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(operation, parsed_args)
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError:
            future.cancel()
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _metadata(
        self,
        attempts: list[dict[str, Any]],
        *,
        max_retries: int | None = None,
        source: str = "mock",
        mock: bool = True,
    ) -> dict[str, Any]:
        return {
            "source": source,
            "mock": mock,
            "attempt_count": len(attempts),
            "max_retries": self.policy.max_retries if max_retries is None else max_retries,
            "timeout_seconds": self.policy.timeout_seconds,
            "attempts": attempts,
        }

    def _ticket_service(self) -> TicketService:
        if self.ticket_service is None:
            self.ticket_service = TicketService()
        return self.ticket_service

    def _create_ticket(self, args: CreateTicketArgs) -> dict[str, Any]:
        # Writes are intentionally single-attempt. Entry idempotency protects the request boundary.
        ticket = self._ticket_service().create_ticket(
            sender_id=args.user_id,
            text=args.description,
            category=args.category,
            metadata={"source": "business_tool"},
        )
        return _ticket_tool_data(ticket)

    def _query_ticket_status(self, args: QueryTicketStatusArgs) -> dict[str, Any]:
        try:
            ticket = self._ticket_service().query_ticket_status(args.ticket_no)
        except TicketNotFoundError as exc:
            raise MockToolError(
                code="TICKET_NOT_FOUND",
                message="Ticket does not exist.",
                retryable=False,
                details={"ticket_no": exc.ticket_no},
            ) from exc
        return _ticket_tool_data(ticket)


_default_service = MockBusinessToolService()


def query_order(order_id: str, *, trace_id: str | None = None) -> ToolCallResult:
    return _default_service.query_order(order_id, trace_id=trace_id)


def query_logistics(order_id: str, *, trace_id: str | None = None) -> ToolCallResult:
    return _default_service.query_logistics(order_id, trace_id=trace_id)


def create_ticket(
    category: str,
    description: str,
    user_id: str,
    *,
    trace_id: str | None = None,
) -> ToolCallResult:
    return _default_service.create_ticket(category, description, user_id, trace_id=trace_id)


def query_ticket_status(ticket_no: str, *, trace_id: str | None = None) -> ToolCallResult:
    return _default_service.query_ticket_status(ticket_no, trace_id=trace_id)


def create_invoice(order_id: str, title: str, *, trace_id: str | None = None) -> ToolCallResult:
    return _default_service.create_invoice(order_id, title, trace_id=trace_id)


def _clean_required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _is_empty_tool_data(data: Any) -> bool:
    if data is None:
        return True
    if isinstance(data, dict) and not data:
        return True
    return False


def _validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for raw in exc.errors():
        item = {key: value for key, value in raw.items() if key not in {"ctx", "url"}}
        loc = item.get("loc")
        if isinstance(loc, tuple):
            item["loc"] = [str(part) for part in loc]
        errors.append(item)
    return errors


def _ticket_tool_data(ticket: Ticket) -> dict[str, Any]:
    return {
        "ticket_id": ticket.ticket_id,
        "ticket_no": ticket.ticket_no,
        "category": ticket.category,
        "description": str(ticket.metadata.get("raw_text") or ticket.summary),
        "user_id": ticket.sender_id,
        "status": ticket.status,
        "priority": ticket.priority,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
    }
