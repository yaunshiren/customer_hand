from __future__ import annotations

from typing import get_type_hints

import pytest

from app.agent.diagnostic.models import (
    ProductContext,
    ProductResolutionStatus,
)
from app.agent.graph import node_product
from app.agent.graph.builder import build_agent_graph
from app.agent.graph.node_product import resolve_product
from app.agent.graph.state import AgentState
from app.core.tracker import DialogueStateTracker


def test_agent_state_declares_product_context() -> None:
    assert get_type_hints(AgentState)["product_context"] is ProductContext


@pytest.mark.parametrize(
    ("message", "expected_status", "expected_model", "expected_matches", "expected_unsupported"),
    [
        ("我的 T7 无法充电", ProductResolutionStatus.RESOLVED, "T7", ("T7",), ()),
        ("机器人清扫一半停了", ProductResolutionStatus.UNKNOWN, None, (), ()),
        (
            "我有 T7 和 G10 两台机器",
            ProductResolutionStatus.CONFLICT,
            None,
            ("T7", "G10"),
            (),
        ),
        (
            "我的设备编号是 B205",
            ProductResolutionStatus.UNSUPPORTED,
            None,
            (),
            ("B205",),
        ),
    ],
)
def test_resolve_product_writes_context_without_changing_route(
    message: str,
    expected_status: ProductResolutionStatus,
    expected_model: str | None,
    expected_matches: tuple[str, ...],
    expected_unsupported: tuple[str, ...],
) -> None:
    result = resolve_product({"message": message, "route": "rag"})
    context = result["product_context"]

    assert context.resolution_status is expected_status
    assert context.model_id == expected_model
    assert context.matched_models == expected_matches
    assert context.unsupported_mentions == expected_unsupported
    assert result["route"] == "rag"


def test_graph_places_resolve_product_between_load_context_and_understand() -> None:
    graph = build_agent_graph().get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert "resolve_product" in graph.nodes
    assert ("load_context", "resolve_product") in edges
    assert ("resolve_product", "understand") in edges
    assert ("load_context", "understand") not in edges
    assert ("understand", "route") in edges


def test_resolve_product_does_not_read_assistant_content() -> None:
    tracker = DialogueStateTracker("assistant-isolation-user")
    tracker.update_with_user_message("上一轮没有说明型号")
    tracker.add_bot_message("assistant 曾经提到 G10S Pro")

    result = resolve_product(
        {
            "message": "当前用户说我的型号是 T7",
            "tracker": tracker,
        }
    )

    context = result["product_context"]
    assert context.resolution_status is ProductResolutionStatus.RESOLVED
    assert context.model_id == "T7"
    assert context.matched_models == ("T7",)


def test_resolve_product_does_not_inherit_previous_context() -> None:
    previous = resolve_product({"message": "我的型号是 G10"})["product_context"]

    result = resolve_product(
        {
            "message": "这次没有说明具体型号",
            "product_context": previous,
        }
    )

    context = result["product_context"]
    assert context.resolution_status is ProductResolutionStatus.UNKNOWN
    assert context.model_id is None
    assert context.matched_models == ()
    assert context.unsupported_mentions == ()


def test_resolve_product_fails_closed_without_fabricating_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_load_parser() -> None:
        raise ValueError("catalog unavailable")

    monkeypatch.setattr(node_product, "_get_product_parser", fail_to_load_parser)

    result = resolve_product({"message": "我的型号是 T7", "route": "rag"})
    context = result["product_context"]

    assert context == ProductContext(resolution_status=ProductResolutionStatus.UNKNOWN)
    assert context.model_id is None
    assert context.matched_models == ()
    assert context.unsupported_mentions == ()
    assert context.evidence == ()
    assert result["route"] == "rag"
