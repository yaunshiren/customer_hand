from __future__ import annotations

import re
import time
from typing import Any

import app.tools.service as tool_service_module
from app.tools import MockBusinessToolService, MockCustomerServiceStore, MockToolError, ToolExecutionPolicy, create_ticket, query_order
from app.tickets.service import TicketService
from app.tickets.store import InMemoryTicketStore


def test_query_order_returns_structured_result() -> None:
    service = MockBusinessToolService()

    result = service.query_order("10001")

    assert result.success is True
    assert result.status == "success"
    assert result.tool_name == "query_order"
    assert result.arguments == {"order_id": "10001"}
    assert result.data is not None
    assert result.data["order_id"] == "10001"
    assert result.data["status"] == "shipped"
    assert result.data["items"][0]["sku"] == "PHONE-14PRO-256-BLACK"
    assert result.error is None
    assert result.metadata["source"] == "mock"
    assert result.metadata["mock"] is True
    assert result.metadata["attempt_count"] == 1


def test_query_logistics_returns_structured_result() -> None:
    service = MockBusinessToolService()

    result = service.query_logistics("10001")

    assert result.success is True
    assert result.tool_name == "query_logistics"
    assert result.data is not None
    assert result.data["order_id"] == "10001"
    assert result.data["status"] == "in_transit"
    assert result.data["carrier"] == "SF Express"
    assert len(result.data["checkpoints"]) == 2


def test_create_ticket_returns_structured_result() -> None:
    service = MockBusinessToolService()

    result = service.create_ticket("complaint", "service attitude was poor", "u_001")

    assert result.success is True
    assert result.tool_name == "create_ticket"
    assert result.data is not None
    assert result.data["ticket_id"]
    assert re.fullmatch(r"TKT-\d{8}-[A-F0-9]{12}", result.data["ticket_no"])
    assert result.data["category"] == "complaint"
    assert result.data["description"] == "service attitude was poor"
    assert result.data["user_id"] == "u_001"
    assert result.data["status"] == "open"
    assert result.data["priority"] == "high"
    assert result.metadata["max_retries"] == 0


def test_query_ticket_status_returns_persisted_ticket_and_records_trace(monkeypatch) -> None:
    traces: list[dict[str, Any]] = []
    monkeypatch.setattr(
        tool_service_module,
        "record_tool_trace",
        lambda **kwargs: traces.append(kwargs),
    )
    service = MockBusinessToolService(
        ticket_service=TicketService(store=InMemoryTicketStore())
    )
    created = service.create_ticket("complaint", "我要投诉客服态度差", "u_001")
    ticket_no = str((created.data or {})["ticket_no"])

    queried = service.query_ticket_status(ticket_no, trace_id="trace-ticket-query")

    assert queried.success is True
    assert queried.data is not None
    assert queried.data["ticket_no"] == ticket_no
    assert queried.data["ticket_id"] == created.data["ticket_id"]
    assert [trace["tool_name"] for trace in traces] == [
        "create_ticket",
        "query_ticket_status",
    ]
    assert traces[-1]["trace_id"] == "trace-ticket-query"


def test_query_ticket_status_not_found_returns_standard_tool_error() -> None:
    service = MockBusinessToolService(
        ticket_service=TicketService(store=InMemoryTicketStore())
    )

    result = service.query_ticket_status("TKT-20260709-FFFFFFFFFFFF")

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "TICKET_NOT_FOUND"
    assert result.error.retryable is False
    assert result.error.details == {
        "ticket_no": "TKT-20260709-FFFFFFFFFFFF",
    }


def test_create_ticket_does_not_retry_on_failure() -> None:
    class FailingTicketService(TicketService):
        def __init__(self) -> None:
            super().__init__(store=InMemoryTicketStore())
            self.calls = 0

        def create_ticket(self, *args: Any, **kwargs: Any):
            self.calls += 1
            raise RuntimeError("ticket database unavailable")

    ticket_service = FailingTicketService()
    service = MockBusinessToolService(
        ticket_service=ticket_service,
        policy=ToolExecutionPolicy(max_retries=3),
    )

    result = service.create_ticket("complaint", "need help", "u_001")

    assert result.success is False
    assert ticket_service.calls == 1
    assert result.metadata["attempt_count"] == 1
    assert result.metadata["max_retries"] == 0


def test_create_invoice_returns_structured_result() -> None:
    service = MockBusinessToolService()

    result = service.create_invoice("10001", "Acme Ltd")

    assert result.success is True
    assert result.tool_name == "create_invoice"
    assert result.arguments == {"order_id": "10001", "title": "Acme Ltd"}
    assert result.data is not None
    assert result.data["invoice_id"].startswith("mock_invoice_")
    assert result.data["order_id"] == "10001"
    assert result.data["title"] == "Acme Ltd"
    assert result.data["status"] == "created"
    assert result.data["amount"] == 3999.0


def test_missing_argument_returns_validation_failure() -> None:
    service = MockBusinessToolService()

    result = service.query_order("   ")

    assert result.success is False
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "TOOL_ARGUMENT_ERROR"
    assert result.error.retryable is False
    assert result.data is None


def test_unknown_order_returns_not_found_failure() -> None:
    service = MockBusinessToolService()

    result = service.query_logistics("missing_order")

    assert result.success is False
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "ORDER_NOT_FOUND"
    assert result.error.details == {"order_id": "missing_order"}


def test_uninvoiceable_order_returns_business_failure() -> None:
    service = MockBusinessToolService()

    result = service.create_invoice("10003", "Acme Ltd")

    assert result.success is False
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "ORDER_NOT_INVOICEABLE"
    assert result.error.details["order_id"] == "10003"


def test_tool_call_records_trace(monkeypatch) -> None:
    traces: list[dict[str, Any]] = []

    def capture(**kwargs: Any) -> None:
        traces.append(kwargs)

    monkeypatch.setattr(tool_service_module, "record_tool_trace", capture)
    service = MockBusinessToolService()

    result = service.query_logistics("10001", trace_id="trace_mock_tool_001")

    assert result.success is True
    assert result.trace_id == "trace_mock_tool_001"
    assert len(traces) == 1
    assert traces[0]["tool_name"] == "query_logistics"
    assert traces[0]["arguments_json"] == {"order_id": "10001"}
    assert traces[0]["result_json"]["success"] is True
    assert traces[0]["result_json"]["metadata"]["attempt_count"] == 1
    assert traces[0]["status"] == "success"
    assert traces[0]["trace_id"] == "trace_mock_tool_001"


def test_tool_timeout_returns_failed_result_and_records_attempts(monkeypatch) -> None:
    class SlowStore(MockCustomerServiceStore):
        def get_logistics(self, order_id: str) -> dict[str, Any]:
            time.sleep(0.05)
            return super().get_logistics(order_id)

    traces: list[dict[str, Any]] = []
    monkeypatch.setattr(tool_service_module, "record_tool_trace", lambda **kwargs: traces.append(kwargs))
    service = MockBusinessToolService(
        store=SlowStore(),
        policy=ToolExecutionPolicy(timeout_seconds=0.001, max_retries=1),
    )

    result = service.query_logistics("10001", trace_id="trace_timeout")

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "TOOL_TIMEOUT"
    assert result.metadata["attempt_count"] == 2
    assert [item["error_code"] for item in result.metadata["attempts"]] == ["TOOL_TIMEOUT", "TOOL_TIMEOUT"]
    assert traces[0]["result_json"]["error"]["code"] == "TOOL_TIMEOUT"
    assert traces[0]["result_json"]["metadata"]["attempt_count"] == 2


def test_empty_tool_result_returns_failed_result(monkeypatch) -> None:
    class EmptyStore(MockCustomerServiceStore):
        def get_order(self, order_id: str) -> dict[str, Any]:
            return {}

    traces: list[dict[str, Any]] = []
    monkeypatch.setattr(tool_service_module, "record_tool_trace", lambda **kwargs: traces.append(kwargs))
    service = MockBusinessToolService(
        store=EmptyStore(),
        policy=ToolExecutionPolicy(timeout_seconds=1.0, max_retries=0),
    )

    result = service.query_order("10001", trace_id="trace_empty")

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "TOOL_EMPTY_RESULT"
    assert result.data is None
    assert result.metadata["attempt_count"] == 1
    assert traces[0]["status"] == "failed"


def test_tool_exception_is_captured_without_crashing(monkeypatch) -> None:
    class FailingStore(MockCustomerServiceStore):
        def get_logistics(self, order_id: str) -> dict[str, Any]:
            raise RuntimeError("logistics backend down")

    traces: list[dict[str, Any]] = []
    monkeypatch.setattr(tool_service_module, "record_tool_trace", lambda **kwargs: traces.append(kwargs))
    service = MockBusinessToolService(
        store=FailingStore(),
        policy=ToolExecutionPolicy(timeout_seconds=1.0, max_retries=1),
    )

    result = service.query_logistics("10001", trace_id="trace_exception")

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "TOOL_FAILURE"
    assert result.error.details["error_type"] == "RuntimeError"
    assert result.metadata["attempt_count"] == 2
    assert traces[0]["result_json"]["error"]["code"] == "TOOL_FAILURE"


def test_retryable_business_error_can_recover(monkeypatch) -> None:
    class FlakyStore(MockCustomerServiceStore):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def get_logistics(self, order_id: str) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                raise MockToolError(
                    code="LOGISTICS_TEMPORARY_UNAVAILABLE",
                    message="temporary logistics outage",
                    retryable=True,
                )
            return super().get_logistics(order_id)

    traces: list[dict[str, Any]] = []
    monkeypatch.setattr(tool_service_module, "record_tool_trace", lambda **kwargs: traces.append(kwargs))
    store = FlakyStore()
    service = MockBusinessToolService(
        store=store,
        policy=ToolExecutionPolicy(timeout_seconds=1.0, max_retries=1),
    )

    result = service.query_logistics("10001", trace_id="trace_retry_success")

    assert result.success is True
    assert store.calls == 2
    assert result.metadata["attempt_count"] == 2
    assert result.metadata["attempts"][0]["error_code"] == "LOGISTICS_TEMPORARY_UNAVAILABLE"
    assert result.metadata["attempts"][1]["status"] == "success"
    assert traces[0]["status"] == "success"


def test_module_level_functions_are_callable() -> None:
    order_result = query_order("10002")
    ticket_result = create_ticket("logistics", "package has no update", "u_002")

    assert order_result.success is True
    assert order_result.data is not None
    assert order_result.data["status"] == "delivered"
    assert ticket_result.success is True
    assert ticket_result.data is not None
    assert ticket_result.data["ticket_id"]
    assert re.fullmatch(r"TKT-\d{8}-[A-F0-9]{12}", ticket_result.data["ticket_no"])
