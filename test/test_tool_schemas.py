from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.llm.prompts import PromptBuilder
from app.tools import (
    get_tool_schema,
    list_function_tool_schemas,
    list_prompt_tool_schemas,
    list_tool_schemas,
    validate_tool_arguments,
)


EXPECTED_TOOL_NAMES = ["query_order", "query_logistics", "create_ticket", "create_invoice"]


def test_list_tool_schemas_exposes_first_batch_tools_in_stable_order() -> None:
    schemas = list_tool_schemas()

    assert [schema.name for schema in schemas] == EXPECTED_TOOL_NAMES
    assert all(schema.description for schema in schemas)
    assert all(schema.parameters["type"] == "object" for schema in schemas)
    assert all(schema.returns["type"] == "object" for schema in schemas)
    assert all(schema.trace_enabled is True for schema in schemas)


@pytest.mark.parametrize(
    ("tool_name", "required"),
    [
        ("query_order", ["order_id"]),
        ("query_logistics", ["order_id"]),
        ("create_ticket", ["category", "description", "user_id"]),
        ("create_invoice", ["order_id", "title"]),
    ],
)
def test_tool_schema_declares_required_arguments(tool_name: str, required: list[str]) -> None:
    schema = get_tool_schema(tool_name)

    assert schema.required == required
    assert schema.parameters["required"] == required
    assert schema.parameters["additionalProperties"] is False
    assert set(schema.parameters["properties"]) == set(required)
    assert schema.when_to_use
    assert schema.when_not_to_use


def test_create_invoice_schema_marks_confirmation_and_medium_risk() -> None:
    schema = get_tool_schema("create_invoice")

    assert schema.requires_confirmation is True
    assert schema.risk_level == "medium"


def test_prompt_tool_schema_shape_is_model_friendly() -> None:
    tools = list_prompt_tool_schemas()
    logistics = next(item for item in tools if item["tool_name"] == "query_logistics")

    assert logistics["description"]
    assert logistics["parameters"]["properties"]["order_id"]["type"] == "string"
    assert logistics["required"] == ["order_id"]
    assert logistics["returns"]["properties"]["data"]["properties"]["carrier"]["type"] == "string"
    assert logistics["examples"][0]["arguments"] == {"order_id": "10001"}


def test_function_tool_schema_shape_is_function_calling_compatible() -> None:
    tools = list_function_tool_schemas()
    first = tools[0]

    assert first["type"] == "function"
    assert first["function"]["name"] == "query_order"
    assert first["function"]["parameters"]["required"] == ["order_id"]


def test_validate_tool_arguments_uses_same_schema_models_as_runtime_tools() -> None:
    parsed = validate_tool_arguments(
        "create_ticket",
        {"category": "complaint", "description": "poor service", "user_id": "u_001"},
    )

    assert parsed == {"category": "complaint", "description": "poor service", "user_id": "u_001"}

    with pytest.raises(ValidationError):
        validate_tool_arguments("query_order", {"order_id": "10001", "extra": "not allowed"})


def test_prompt_builder_default_tools_come_from_business_tool_schema_registry() -> None:
    prompt = PromptBuilder().build(tracker={}, user_message="check order 10001")[1]

    assert "query_order" in prompt
    assert "query_logistics" in prompt
    assert "create_ticket" in prompt
    assert "create_invoice" in prompt
    assert "get_logistics_info" not in prompt
