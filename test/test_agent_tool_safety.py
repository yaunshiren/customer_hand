from __future__ import annotations

from typing import Any

from app.agent.agent import Agent
from app.agent.graph import nodes
from app.agent.tool_safety import AgentToolSafetyPolicy
from app.core.tracker_store import InMemoryTrackerStore
from app.rag.answerer import KnowledgeAnswerer
from app.tools import MockBusinessToolService


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


def _agent(policy: AgentToolSafetyPolicy | None = None) -> Agent:
    agent = Agent(
        tracker_store=InMemoryTrackerStore(),
        flows={},
        tool_safety_policy=policy,
    )
    agent.llm_generator.client.enabled = False
    agent.knowledge_answerer = FakeKnowledgeAnswerer()
    return agent


def test_high_risk_invoice_requires_confirmation_then_executes() -> None:
    agent = _agent()

    first = agent.handle_message(
        "\u8ba2\u5355 10001 \u5f00\u516c\u53f8\u53d1\u7968",
        "safe_invoice_user",
    )
    first_metadata = first[0]["metadata"]

    assert first_metadata["route"] == "clarify"
    assert first_metadata["business_tool"] == "create_invoice"
    assert first_metadata["business_requires_confirmation"] is True
    assert first_metadata["tool_safety_decision"] == "confirmation_required"
    assert first_metadata.get("tool_name") is None
    assert "\u786e\u8ba4" in first[0]["text"]

    second = agent.handle_message("\u786e\u8ba4", "safe_invoice_user")
    second_metadata = second[0]["metadata"]

    assert second_metadata["route"] == "tool"
    assert second_metadata["business_source"] == "tool_confirmation"
    assert second_metadata["tool_safety_decision"] == "confirmed"
    assert second_metadata["tool_name"] == "create_invoice"
    assert second_metadata["tool_success"] is True
    assert second_metadata["tool_arguments"] == {"order_id": "10001", "title": "\u516c\u53f8"}


def test_pending_high_risk_tool_can_be_cancelled_without_execution() -> None:
    agent = _agent()

    agent.handle_message(
        "\u8ba2\u5355 10001 \u5f00\u516c\u53f8\u53d1\u7968",
        "cancel_invoice_user",
    )
    response = agent.handle_message("\u53d6\u6d88", "cancel_invoice_user")
    metadata = response[0]["metadata"]

    assert metadata["route"] == "clarify"
    assert metadata["tool_safety_decision"] == "confirmation_cancelled"
    assert metadata["pending_tool_name"] == "create_invoice"
    assert metadata.get("tool_name") is None
    assert "\u5df2\u53d6\u6d88" in response[0]["text"]


def test_repeated_tool_call_is_blocked_in_same_turn() -> None:
    state: dict[str, Any] = {
        "tool_safety_policy": AgentToolSafetyPolicy(max_tool_calls_per_turn=3),
        "tool_call_fingerprints": [],
    }

    first = nodes._invoke_business_tool(state, "query_order", {"order_id": "10001"})
    second = nodes._invoke_business_tool(state, "query_order", {"order_id": "10001"})

    assert first.success is True
    assert second.success is False
    assert second.error is not None
    assert second.error.code == "TOOL_REPEATED_CALL"
    assert second.metadata["safety_reason"] == "duplicate_tool_call"


def test_max_tool_calls_per_turn_blocks_second_distinct_call() -> None:
    state: dict[str, Any] = {
        "tool_safety_policy": AgentToolSafetyPolicy(max_tool_calls_per_turn=1),
        "tool_call_fingerprints": [],
    }

    first = nodes._invoke_business_tool(state, "query_order", {"order_id": "10001"})
    second = nodes._invoke_business_tool(state, "query_logistics", {"order_id": "10001"})

    assert first.success is True
    assert second.success is False
    assert second.error is not None
    assert second.error.code == "TOOL_CALL_LIMIT_EXCEEDED"
    assert second.error.details == {"max_tool_calls_per_turn": 1}


def test_agent_safety_policy_configures_default_mock_tool_service() -> None:
    service = nodes._build_business_tool_service(
        {
            "tool_safety_policy": AgentToolSafetyPolicy(
                tool_timeout_seconds=0.25,
                max_tool_retries=2,
                retry_backoff_seconds=0.01,
            )
        }
    )

    assert isinstance(service, MockBusinessToolService)
    assert service.policy.timeout_seconds == 0.25
    assert service.policy.max_retries == 2
    assert service.policy.retry_backoff_seconds == 0.01
