from __future__ import annotations

from typing import Any

from app.agent.agent import Agent
from app.core.tracker_store import InMemoryTrackerStore
from app.llm.client import LLMClient
from app.llm.prompts import PromptBuilder
from app.rag.answerer import KnowledgeAnswerer


class ExplodingLLMClient:
    enabled = True

    def generate_json(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise AssertionError("deterministic business routes should not call the LLM")


class ExplodingLLMGenerator:
    client = ExplodingLLMClient()
    enabled = True

    def generate(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise AssertionError("deterministic business routes should not call command generation")


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


def _agent_with_exploding_llm() -> Agent:
    agent = Agent(tracker_store=InMemoryTrackerStore(), flows={})
    agent.llm_generator = ExplodingLLMGenerator()
    agent.knowledge_answerer = FakeKnowledgeAnswerer()
    return agent


def test_business_tool_route_skips_intent_and_command_llm_calls() -> None:
    response = _agent_with_exploding_llm().handle_message(
        "\u67e5\u4e00\u4e0b\u8ba2\u5355 10001 \u5230\u54ea\u4e86",
        "token_budget_tool_user",
    )
    metadata = response[0]["metadata"]

    assert metadata["route"] == "tool"
    assert metadata["tool_name"] == "query_logistics"
    assert metadata["tool_success"] is True


def test_business_rag_route_skips_intent_and_command_llm_calls() -> None:
    response = _agent_with_exploding_llm().handle_message(
        "\u600e\u4e48\u5f00\u53d1\u7968",
        "token_budget_rag_user",
    )
    metadata = response[0]["metadata"]

    assert metadata["route"] == "rag"
    assert metadata["business_question_type"] == "invoice_policy"
    assert response[0]["text"] == "test knowledge answer"


def test_command_prompt_uses_compact_tool_descriptions() -> None:
    prompt = PromptBuilder().build(tracker={}, user_message="check order 10001")[1]

    assert "query_logistics" in prompt
    assert "create_invoice" in prompt
    assert "returns" not in prompt
    assert len(prompt) < 6000


def test_llm_client_disables_smoke_test_and_retries_by_default() -> None:
    client = LLMClient(enabled=True, api_key="test", base_url="http://example.com", model="test")

    assert client.max_retries == 0
    assert client.smoke_test_enabled is False
