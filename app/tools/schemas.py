from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.tools.service import (
    CreateInvoiceArgs,
    CreateTicketArgs,
    QueryLogisticsArgs,
    QueryOrderArgs,
    QueryTicketStatusArgs,
)


RiskLevel = Literal["low", "medium", "high"]


class ToolExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_text: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class BusinessToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    returns: dict[str, Any] = Field(default_factory=dict)
    when_to_use: list[str] = Field(default_factory=list)
    when_not_to_use: list[str] = Field(default_factory=list)
    examples: list[ToolExample] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    requires_confirmation: bool = False
    trace_enabled: bool = True

    def to_prompt_schema(self) -> dict[str, Any]:
        return {
            "tool_name": self.name,
            "description": self.description,
            "parameters": deepcopy(self.parameters),
            "required": list(self.required),
            "returns": deepcopy(self.returns),
            "when_to_use": list(self.when_to_use),
            "when_not_to_use": list(self.when_not_to_use),
            "examples": [example.model_dump(mode="json") for example in self.examples],
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "trace_enabled": self.trace_enabled,
        }

    def to_function_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": deepcopy(self.parameters),
            },
        }


ARGUMENT_MODELS: dict[str, type[BaseModel]] = {
    "query_order": QueryOrderArgs,
    "query_logistics": QueryLogisticsArgs,
    "create_ticket": CreateTicketArgs,
    "query_ticket_status": QueryTicketStatusArgs,
    "create_invoice": CreateInvoiceArgs,
}


def list_tool_schemas() -> list[BusinessToolSchema]:
    return [get_tool_schema(name) for name in TOOL_ORDER]


def list_prompt_tool_schemas() -> list[dict[str, Any]]:
    return [schema.to_prompt_schema() for schema in list_tool_schemas()]


def list_function_tool_schemas() -> list[dict[str, Any]]:
    return [schema.to_function_schema() for schema in list_tool_schemas()]


def get_tool_schema(name: str) -> BusinessToolSchema:
    schema = TOOL_SCHEMAS.get(name)
    if schema is None:
        raise KeyError(f"unknown tool schema: {name}")
    return schema.model_copy(deep=True)


def validate_tool_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    model = ARGUMENT_MODELS.get(name)
    if model is None:
        raise KeyError(f"unknown tool argument model: {name}")
    return model.model_validate(arguments).model_dump(mode="json")


def _argument_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    return {
        "type": "object",
        "properties": deepcopy(schema.get("properties") or {}),
        "required": list(schema.get("required") or []),
        "additionalProperties": bool(schema.get("additionalProperties", False)),
    }


def _required(model: type[BaseModel]) -> list[str]:
    return list(model.model_json_schema().get("required") or [])


def _result_schema(data_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["tool_name", "success", "status", "arguments", "data", "error", "latency_ms"],
        "properties": {
            "tool_name": {"type": "string"},
            "success": {"type": "boolean"},
            "status": {"type": "string", "enum": ["success", "failed"]},
            "arguments": {"type": "object"},
            "data": data_schema,
            "error": {
                "type": ["object", "null"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "retryable": {"type": "boolean"},
                    "details": {"type": "object"},
                },
            },
            "latency_ms": {"type": "integer", "minimum": 0},
            "trace_id": {"type": ["string", "null"]},
            "metadata": {"type": "object"},
        },
    }


ORDER_DATA_SCHEMA = {
    "type": ["object", "null"],
    "required": ["order_id", "user_id", "status", "payment_status", "total_amount", "currency", "items"],
    "properties": {
        "order_id": {"type": "string"},
        "user_id": {"type": "string"},
        "status": {"type": "string"},
        "payment_status": {"type": "string"},
        "total_amount": {"type": "number"},
        "currency": {"type": "string"},
        "created_at": {"type": "string"},
        "invoiceable": {"type": "boolean"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["sku", "name", "quantity", "unit_price"],
                "properties": {
                    "sku": {"type": "string"},
                    "name": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "unit_price": {"type": "number"},
                },
            },
        },
    },
}


LOGISTICS_DATA_SCHEMA = {
    "type": ["object", "null"],
    "required": ["order_id", "status", "carrier", "tracking_no", "current_location", "updated_at"],
    "properties": {
        "order_id": {"type": "string"},
        "status": {"type": "string"},
        "carrier": {"type": "string"},
        "tracking_no": {"type": "string"},
        "current_location": {"type": "string"},
        "estimated_delivery": {"type": "string"},
        "updated_at": {"type": "string"},
        "checkpoints": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["time", "location", "description"],
                "properties": {
                    "time": {"type": "string"},
                    "location": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
    },
}


TICKET_DATA_SCHEMA = {
    "type": ["object", "null"],
    "required": ["ticket_id", "ticket_no", "category", "description", "user_id", "status", "priority", "created_at"],
    "properties": {
        "ticket_id": {"type": "string"},
        "ticket_no": {"type": "string"},
        "category": {"type": "string"},
        "description": {"type": "string"},
        "user_id": {"type": "string"},
        "status": {"type": "string"},
        "priority": {"type": "string"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
    },
}


INVOICE_DATA_SCHEMA = {
    "type": ["object", "null"],
    "required": ["invoice_id", "order_id", "title", "invoice_type", "status", "amount", "currency", "created_at"],
    "properties": {
        "invoice_id": {"type": "string"},
        "order_id": {"type": "string"},
        "title": {"type": "string"},
        "invoice_type": {"type": "string"},
        "status": {"type": "string"},
        "amount": {"type": "number"},
        "currency": {"type": "string"},
        "created_at": {"type": "string"},
    },
}


TOOL_ORDER = (
    "query_order",
    "query_logistics",
    "create_ticket",
    "query_ticket_status",
    "create_invoice",
)

TOOL_SCHEMAS: dict[str, BusinessToolSchema] = {
    "query_order": BusinessToolSchema(
        name="query_order",
        description="Query an individual order by order_id and return order status, payment status, amount, and items.",
        parameters=_argument_schema(QueryOrderArgs),
        required=_required(QueryOrderArgs),
        returns=_result_schema(ORDER_DATA_SCHEMA),
        when_to_use=[
            "The user asks about a personal order status or order details.",
            "The user provides an order id and asks what was bought or whether payment/order status is complete.",
        ],
        when_not_to_use=[
            "The user asks general order policy, such as how long shipment normally takes; use RAG instead.",
            "The user does not provide an order id; ask for order_id first.",
        ],
        examples=[
            ToolExample(user_text="Check order 10001", arguments={"order_id": "10001"}),
            ToolExample(user_text="What is the status of my order 10002?", arguments={"order_id": "10002"}),
        ],
        risk_level="low",
    ),
    "query_logistics": BusinessToolSchema(
        name="query_logistics",
        description="Query logistics status for a specific order_id, including carrier, tracking number, location, and checkpoints.",
        parameters=_argument_schema(QueryLogisticsArgs),
        required=_required(QueryLogisticsArgs),
        returns=_result_schema(LOGISTICS_DATA_SCHEMA),
        when_to_use=[
            "The user asks where a specific order or package is.",
            "The user provides an order id and asks about delivery, shipping, carrier, or logistics progress.",
        ],
        when_not_to_use=[
            "The user asks general shipping rules or delivery policy; use RAG instead.",
            "The user does not provide an order id; ask for order_id first.",
        ],
        examples=[
            ToolExample(user_text="Where is order 10001?", arguments={"order_id": "10001"}),
            ToolExample(user_text="Check logistics for 10002", arguments={"order_id": "10002"}),
        ],
        risk_level="low",
    ),
    "create_ticket": BusinessToolSchema(
        name="create_ticket",
        description="Create a customer service ticket for complaints, unresolved issues, or requests needing human follow-up.",
        parameters=_argument_schema(CreateTicketArgs),
        required=_required(CreateTicketArgs),
        returns=_result_schema(TICKET_DATA_SCHEMA),
        when_to_use=[
            "The user explicitly complains or asks to escalate to human support.",
            "The issue cannot be resolved automatically and needs follow-up.",
        ],
        when_not_to_use=[
            "The user asks a simple policy question that RAG can answer.",
            "The user only asks for order or logistics lookup and required parameters are present.",
        ],
        examples=[
            ToolExample(
                user_text="I want to complain about poor service attitude",
                arguments={
                    "category": "complaint",
                    "description": "I want to complain about poor service attitude",
                    "user_id": "u_001",
                },
            )
        ],
        risk_level="low",
    ),
    "query_ticket_status": BusinessToolSchema(
        name="query_ticket_status",
        description="Query the current status of an existing customer service ticket by ticket_no.",
        parameters=_argument_schema(QueryTicketStatusArgs),
        required=_required(QueryTicketStatusArgs),
        returns=_result_schema(TICKET_DATA_SCHEMA),
        when_to_use=[
            "The user provides a ticket number and explicitly asks for its current status or progress.",
        ],
        when_not_to_use=[
            "The user asks how to create a ticket or asks a general ticket policy question.",
            "No explicit ticket number is present.",
        ],
        examples=[
            ToolExample(
                user_text="What is the status of ticket TKT-20260709-A1B2C3D4E5F6?",
                arguments={"ticket_no": "TKT-20260709-A1B2C3D4E5F6"},
            )
        ],
        risk_level="low",
    ),
    "create_invoice": BusinessToolSchema(
        name="create_invoice",
        description="Create an electronic invoice for an invoiceable order with a specific invoice title.",
        parameters=_argument_schema(CreateInvoiceArgs),
        required=_required(CreateInvoiceArgs),
        returns=_result_schema(INVOICE_DATA_SCHEMA),
        when_to_use=[
            "The user asks to issue an invoice for a specific order and provides invoice title.",
            "The user intent is invoice creation, not just asking how invoices work.",
        ],
        when_not_to_use=[
            "The user asks how to issue an invoice or where invoice entry is; use RAG instead.",
            "The order_id or title is missing; ask for missing fields first.",
        ],
        examples=[
            ToolExample(user_text="Issue a company invoice for order 10001", arguments={"order_id": "10001", "title": "Company"}),
            ToolExample(user_text="Create invoice for 10002 with title Acme Ltd", arguments={"order_id": "10002", "title": "Acme Ltd"}),
        ],
        risk_level="medium",
        requires_confirmation=True,
    ),
}
