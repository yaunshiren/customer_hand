from __future__ import annotations

from typing import Any

import app.tools.service as tool_service_module
from app.tools import MockBusinessToolService, create_ticket, query_order


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
    assert result.metadata == {"source": "mock", "mock": True}


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
    assert result.data["ticket_id"].startswith("mock_ticket_")
    assert result.data["category"] == "complaint"
    assert result.data["description"] == "service attitude was poor"
    assert result.data["user_id"] == "u_001"
    assert result.data["status"] == "open"
    assert result.data["priority"] == "high"


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
    assert traces[0]["status"] == "success"
    assert traces[0]["trace_id"] == "trace_mock_tool_001"


def test_module_level_functions_are_callable() -> None:
    order_result = query_order("10002")
    ticket_result = create_ticket("logistics", "package has no update", "u_002")

    assert order_result.success is True
    assert order_result.data is not None
    assert order_result.data["status"] == "delivered"
    assert ticket_result.success is True
    assert ticket_result.data is not None
    assert ticket_result.data["ticket_id"].startswith("mock_ticket_")
