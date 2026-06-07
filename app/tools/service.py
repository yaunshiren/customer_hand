from __future__ import annotations

import time
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.trace import get_trace_id
from app.persistence.tool_recorder import record_tool_trace
from app.tools.mock_store import MockCustomerServiceStore, MockToolError
from app.tools.models import ToolCallResult, ToolError


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


class CreateInvoiceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, description="Order id that needs an invoice.")
    title: str = Field(min_length=1, description="Invoice title, such as a company or personal title.")

    @field_validator("order_id", "title")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _clean_required_text(value, info.field_name)


class MockBusinessToolService:
    def __init__(self, store: MockCustomerServiceStore | None = None) -> None:
        self.store = store or MockCustomerServiceStore()

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
            operation=lambda args: self.store.create_ticket(
                category=args.category,
                description=args.description,
                user_id=args.user_id,
            ),
            trace_id=trace_id,
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
    ) -> ToolCallResult:
        started_at = time.perf_counter()
        effective_trace_id = trace_id or get_trace_id()
        arguments = dict(raw_arguments)

        try:
            parsed_args = args_model.model_validate(raw_arguments)
            arguments = parsed_args.model_dump(mode="json")
            data = operation(parsed_args)
            result = ToolCallResult(
                tool_name=tool_name,
                success=True,
                status="success",
                arguments=arguments,
                data=data,
                latency_ms=_elapsed_ms(started_at),
                trace_id=effective_trace_id,
                metadata={"source": "mock", "mock": True},
            )
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
            )
        except MockToolError as exc:
            result = self._failed_result(
                tool_name=tool_name,
                arguments=arguments,
                started_at=started_at,
                trace_id=effective_trace_id,
                error=ToolError(
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                    details=exc.details,
                ),
            )
        except Exception as exc:
            result = self._failed_result(
                tool_name=tool_name,
                arguments=arguments,
                started_at=started_at,
                trace_id=effective_trace_id,
                error=ToolError(
                    code="TOOL_FAILURE",
                    message=str(exc) or exc.__class__.__name__,
                    retryable=True,
                    details={"error_type": exc.__class__.__name__},
                ),
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
            metadata={"source": "mock", "mock": True},
        )


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


def create_invoice(order_id: str, title: str, *, trace_id: str | None = None) -> ToolCallResult:
    return _default_service.create_invoice(order_id, title, trace_id=trace_id)


def _clean_required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for raw in exc.errors():
        item = {key: value for key, value in raw.items() if key not in {"ctx", "url"}}
        loc = item.get("loc")
        if isinstance(loc, tuple):
            item["loc"] = [str(part) for part in loc]
        errors.append(item)
    return errors
