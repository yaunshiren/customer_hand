from __future__ import annotations

from typing import Any

from app.agent.graph import node_execution as _execution
from app.agent.graph import node_tooling as _tooling
from app.agent.graph.node_context import load_context, save_context
from app.agent.graph.node_execution import flow
from app.agent.graph.node_rag import rag
from app.agent.graph.node_response import generate_response
from app.agent.graph.node_routing import route
from app.agent.graph.node_services import _build_business_tool_service
from app.agent.graph.node_understanding import understand
from app.persistence.tool_recorder import record_tool_trace


def _sync_compat_patches() -> None:
    _execution.record_tool_trace = record_tool_trace
    _tooling.record_tool_trace = record_tool_trace


def action(state: dict[str, Any]) -> dict[str, Any]:
    _sync_compat_patches()
    return _execution.action(state)


def ticket(state: dict[str, Any]) -> dict[str, Any]:
    _sync_compat_patches()
    return _execution.ticket(state)


def tool(state: dict[str, Any]) -> dict[str, Any]:
    _sync_compat_patches()
    return _execution.tool(state)


def _invoke_business_tool(state: dict[str, Any], tool_name: str, arguments: dict[str, Any]):
    _sync_compat_patches()
    return _tooling._invoke_business_tool(state, tool_name, arguments)


__all__ = [
    "load_context",
    "understand",
    "route",
    "rag",
    "flow",
    "action",
    "tool",
    "ticket",
    "generate_response",
    "save_context",
]
