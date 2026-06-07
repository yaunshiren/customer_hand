from __future__ import annotations

import time
from typing import Any

from app.agent.agent import Agent
from app.agent.graph import nodes
from app.core.tracker_store import InMemoryTrackerStore
from app.rag.answerer import KnowledgeAnswerer
from app.tools import MockBusinessToolService, MockCustomerServiceStore, ToolExecutionPolicy


class FakeKnowledgeAnswerer(KnowledgeAnswerer):
    def __init__(self) -> None:
        pass

    def answer(self, question: str, top_k: int = 3, **_: object) -> dict[str, object]:
        return {
            "question": question,
            "answer": "test knowledge answer",
            "matches": [],
            "used_llm": False,
        }


def _agent(tool_service: Any) -> Agent:
    agent = Agent(tracker_store=InMemoryTrackerStore(), flows={})
    agent.llm_generator.client.enabled = False
    agent.knowledge_answerer = FakeKnowledgeAnswerer()
    agent.business_tool_service = tool_service
    return agent


def test_tool_timeout_degrades_without_crashing() -> None:
    class SlowStore(MockCustomerServiceStore):
        def get_logistics(self, order_id: str) -> dict[str, Any]:
            time.sleep(0.05)
            return super().get_logistics(order_id)

    service = MockBusinessToolService(
        store=SlowStore(),
        policy=ToolExecutionPolicy(timeout_seconds=0.001, max_retries=1),
    )

    response = _agent(service).handle_message(
        "\u67e5\u4e00\u4e0b\u8ba2\u5355 10001 \u5230\u54ea\u4e86",
        "tool_timeout_user",
    )
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["tool_name"] == "query_logistics"
    assert metadata["tool_success"] is False
    assert metadata["tool_error_code"] == "TOOL_TIMEOUT"
    assert metadata["tool_attempt_count"] == 2
    assert metadata["tool_timeout_seconds"] == 0.001
    assert "\u8d85\u65f6" in response[0]["text"]


def test_empty_tool_result_degrades_without_crashing() -> None:
    class EmptyStore(MockCustomerServiceStore):
        def get_order(self, order_id: str) -> dict[str, Any]:
            return {}

    service = MockBusinessToolService(
        store=EmptyStore(),
        policy=ToolExecutionPolicy(timeout_seconds=1.0, max_retries=0),
    )

    response = _agent(service).handle_message(
        "\u5e2e\u6211\u67e5\u8be2\u8ba2\u5355 10001 \u7684\u72b6\u6001",
        "tool_empty_user",
    )
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["tool_name"] == "query_order"
    assert metadata["tool_success"] is False
    assert metadata["tool_error_code"] == "TOOL_EMPTY_RESULT"
    assert metadata["tool_attempt_count"] == 1
    assert "\u6ca1\u6709\u67e5\u5230" in response[0]["text"]


def test_tool_exception_degrades_without_crashing() -> None:
    class FailingStore(MockCustomerServiceStore):
        def get_logistics(self, order_id: str) -> dict[str, Any]:
            raise RuntimeError("logistics backend down")

    service = MockBusinessToolService(
        store=FailingStore(),
        policy=ToolExecutionPolicy(timeout_seconds=1.0, max_retries=1),
    )

    response = _agent(service).handle_message(
        "\u67e5\u4e00\u4e0b\u8ba2\u5355 10001 \u5230\u54ea\u4e86",
        "tool_exception_user",
    )
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["tool_name"] == "query_logistics"
    assert metadata["tool_success"] is False
    assert metadata["tool_error_code"] == "TOOL_FAILURE"
    assert metadata["tool_attempt_count"] == 2
    assert response[0]["text"]


def test_router_level_tool_exception_records_trace(monkeypatch: Any) -> None:
    class RaisingToolService:
        def query_logistics(self, order_id: str) -> object:
            raise RuntimeError("tool adapter crashed")

    traces: list[dict[str, Any]] = []
    monkeypatch.setattr(nodes, "record_tool_trace", lambda **kwargs: traces.append(kwargs))

    response = _agent(RaisingToolService()).handle_message(
        "\u67e5\u4e00\u4e0b\u8ba2\u5355 10001 \u5230\u54ea\u4e86",
        "tool_router_exception_user",
    )
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["tool_name"] == "query_logistics"
    assert metadata["tool_success"] is False
    assert metadata["tool_error_code"] == "TOOL_FAILURE"
    assert metadata["tool_attempt_count"] == 1
    assert len(traces) == 1
    assert traces[0]["tool_name"] == "query_logistics"
    assert traces[0]["status"] == "failed"
    assert traces[0]["result_json"]["error"]["code"] == "TOOL_FAILURE"
