from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class MockToolError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


@dataclass
class MockCustomerServiceStore:
    orders: dict[str, dict[str, Any]] = field(default_factory=lambda: deepcopy(DEFAULT_ORDERS))
    logistics: dict[str, dict[str, Any]] = field(default_factory=lambda: deepcopy(DEFAULT_LOGISTICS))
    tickets: dict[str, dict[str, Any]] = field(default_factory=dict)
    invoices: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get_order(self, order_id: str) -> dict[str, Any]:
        order = self.orders.get(order_id)
        if order is None:
            raise MockToolError(
                code="ORDER_NOT_FOUND",
                message="Order does not exist in mock data.",
                details={"order_id": order_id},
            )
        return deepcopy(order)

    def get_logistics(self, order_id: str) -> dict[str, Any]:
        self.get_order(order_id)
        logistics = self.logistics.get(order_id)
        if logistics is None:
            raise MockToolError(
                code="LOGISTICS_NOT_FOUND",
                message="Logistics status is not available for this order.",
                details={"order_id": order_id},
            )
        return deepcopy(logistics)

    def create_ticket(self, *, category: str, description: str, user_id: str) -> dict[str, Any]:
        ticket_id = f"mock_ticket_{uuid4().hex[:12]}"
        now = _now_iso()
        ticket = {
            "ticket_id": ticket_id,
            "category": category,
            "description": description,
            "user_id": user_id,
            "status": "open",
            "priority": _ticket_priority(category, description),
            "created_at": now,
            "updated_at": now,
        }
        self.tickets[ticket_id] = deepcopy(ticket)
        return ticket

    def create_invoice(self, *, order_id: str, title: str) -> dict[str, Any]:
        order = self.get_order(order_id)
        if not order.get("invoiceable", False):
            raise MockToolError(
                code="ORDER_NOT_INVOICEABLE",
                message="Order is not invoiceable in its current mock status.",
                details={"order_id": order_id, "order_status": order.get("status")},
            )

        invoice_id = f"mock_invoice_{uuid4().hex[:12]}"
        invoice = {
            "invoice_id": invoice_id,
            "order_id": order_id,
            "title": title,
            "invoice_type": "electronic",
            "status": "created",
            "amount": order["total_amount"],
            "currency": order["currency"],
            "created_at": _now_iso(),
        }
        self.invoices[invoice_id] = deepcopy(invoice)
        return invoice


def _ticket_priority(category: str, description: str) -> str:
    text = f"{category} {description}".casefold()
    if any(term in text for term in ("complaint", "refund", "broken", "angry")):
        return "high"
    return "normal"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_ORDERS: dict[str, dict[str, Any]] = {
    "10001": {
        "order_id": "10001",
        "user_id": "u_10001",
        "status": "shipped",
        "payment_status": "paid",
        "total_amount": 3999.0,
        "currency": "CNY",
        "created_at": "2026-06-01T10:20:00+08:00",
        "invoiceable": True,
        "items": [
            {
                "sku": "PHONE-14PRO-256-BLACK",
                "name": "BitSelect Phone 14 Pro 256G Black",
                "quantity": 1,
                "unit_price": 3999.0,
            }
        ],
    },
    "10002": {
        "order_id": "10002",
        "user_id": "u_10002",
        "status": "delivered",
        "payment_status": "paid",
        "total_amount": 899.0,
        "currency": "CNY",
        "created_at": "2026-06-02T15:30:00+08:00",
        "invoiceable": True,
        "items": [
            {
                "sku": "BUDS-PRO-WHITE",
                "name": "BitSelect Buds Pro White",
                "quantity": 1,
                "unit_price": 899.0,
            }
        ],
    },
    "10003": {
        "order_id": "10003",
        "user_id": "u_10003",
        "status": "pending_payment",
        "payment_status": "unpaid",
        "total_amount": 1299.0,
        "currency": "CNY",
        "created_at": "2026-06-03T09:10:00+08:00",
        "invoiceable": False,
        "items": [
            {
                "sku": "WATCH-S2-GRAY",
                "name": "BitSelect Watch S2 Gray",
                "quantity": 1,
                "unit_price": 1299.0,
            }
        ],
    },
}


DEFAULT_LOGISTICS: dict[str, dict[str, Any]] = {
    "10001": {
        "order_id": "10001",
        "status": "in_transit",
        "carrier": "SF Express",
        "tracking_no": "SF100010001",
        "current_location": "Shanghai sorting center",
        "estimated_delivery": "2026-06-08",
        "updated_at": "2026-06-07T09:30:00+08:00",
        "checkpoints": [
            {
                "time": "2026-06-06T18:20:00+08:00",
                "location": "Hangzhou warehouse",
                "description": "Package has left the warehouse.",
            },
            {
                "time": "2026-06-07T09:30:00+08:00",
                "location": "Shanghai sorting center",
                "description": "Package is being sorted for delivery.",
            },
        ],
    },
    "10002": {
        "order_id": "10002",
        "status": "delivered",
        "carrier": "JD Logistics",
        "tracking_no": "JD100020002",
        "current_location": "Delivered",
        "estimated_delivery": "2026-06-05",
        "updated_at": "2026-06-05T14:05:00+08:00",
        "checkpoints": [
            {
                "time": "2026-06-04T20:15:00+08:00",
                "location": "Beijing distribution center",
                "description": "Package has arrived at the distribution center.",
            },
            {
                "time": "2026-06-05T14:05:00+08:00",
                "location": "Customer address",
                "description": "Package has been delivered and signed for.",
            },
        ],
    },
}
