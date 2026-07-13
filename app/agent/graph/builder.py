from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.graph.nodes import (
    action,
    flow,
    generate_response,
    load_context,
    rag,
    resolve_product,
    route,
    save_context,
    ticket,
    tool,
    understand,
)
from app.agent.graph.state import AgentState

logger = logging.getLogger(__name__)

_graph_instance: CompiledStateGraph | None = None


def _route_decision(state: AgentState) -> Literal["ticket", "rag", "flow", "action", "tool", "chitchat", "clarify", "fallback"]:
    return str(state.get("route") or "fallback")  # type: ignore[return-value]


def build_agent_graph() -> CompiledStateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("load_context", load_context)
    graph.add_node("resolve_product", resolve_product)
    graph.add_node("understand", understand)
    graph.add_node("route", route)
    graph.add_node("ticket", ticket)
    graph.add_node("rag", rag)
    graph.add_node("flow", flow)
    graph.add_node("action", action)
    graph.add_node("tool", tool)
    graph.add_node("generate_response", generate_response)
    graph.add_node("save_context", save_context)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "resolve_product")
    graph.add_edge("resolve_product", "understand")
    graph.add_edge("understand", "route")

    graph.add_conditional_edges(
        "route",
        _route_decision,
        {
            "ticket": "ticket",
            "rag": "rag",
            "flow": "flow",
            "action": "action",
            "tool": "tool",
            "chitchat": "generate_response",
            "clarify": "generate_response",
            "fallback": "generate_response",
        },
    )

    graph.add_edge("ticket", "generate_response")
    graph.add_edge("rag", "generate_response")
    graph.add_edge("flow", "action")
    graph.add_edge("action", "generate_response")
    graph.add_edge("tool", "generate_response")
    graph.add_edge("generate_response", "save_context")
    graph.add_edge("save_context", END)

    return graph.compile()


def get_agent_graph() -> CompiledStateGraph:
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_agent_graph()
    return _graph_instance


def run_agent_graph(state: AgentState) -> AgentState:
    return get_agent_graph().invoke(state)
