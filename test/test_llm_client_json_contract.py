from __future__ import annotations

from types import MethodType, SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field

from app.llm.client import LLMClient


class CommandPayload(BaseModel):
    commands: list[dict[str, Any]] = Field(default_factory=list)


class FakeCompletions:
    def __init__(self, raw_output: str) -> None:
        self.raw_output = raw_output
        self.kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.raw_output),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=3,
                completion_tokens=2,
                total_tokens=5,
            ),
        )


class FakeOpenAIClient:
    def __init__(self, raw_output: str) -> None:
        self.completions = FakeCompletions(raw_output)
        self.chat = SimpleNamespace(completions=self.completions)


def _client_with_response(raw_output: str) -> tuple[LLMClient, FakeOpenAIClient]:
    client = LLMClient(
        enabled=True,
        api_key="test-key",
        base_url="http://example.test/v1",
        model="fake-model",
    )
    fake_openai = FakeOpenAIClient(raw_output)

    def _build_client(self: LLMClient) -> FakeOpenAIClient:
        return fake_openai

    client._build_client = MethodType(_build_client, client)  # type: ignore[method-assign]
    return client, fake_openai


def test_generate_json_passes_response_format_and_validates_model() -> None:
    client, fake_openai = _client_with_response('{"commands":[]}')

    result = client.generate_json(
        system_prompt="system",
        user_prompt="user",
        response_format={"type": "json_object"},
        response_model=CommandPayload,
    )

    assert result["success"] is True
    assert result["json_output"] == {"commands": []}
    assert result["usage"]["total_tokens"] == 5
    assert fake_openai.completions.kwargs is not None
    assert fake_openai.completions.kwargs["response_format"] == {"type": "json_object"}


def test_generate_json_returns_failure_when_payload_breaks_schema() -> None:
    client, _ = _client_with_response('{"commands":"not-a-list"}')

    result = client.generate_json(
        system_prompt="system",
        user_prompt="user",
        response_format={"type": "json_object"},
        response_model=CommandPayload,
    )

    assert result["success"] is False
    assert result["raw_output"] == '{"commands":"not-a-list"}'
    assert "LLM JSON validation failed for CommandPayload" in str(result["error"])


def test_generate_json_can_build_json_schema_response_format() -> None:
    client, fake_openai = _client_with_response('{"commands":[]}')

    result = client.generate_json(
        system_prompt="system",
        user_prompt="user",
        response_model=CommandPayload,
        use_json_schema=True,
        json_schema_name="Command Payload",
    )

    assert result["success"] is True
    assert fake_openai.completions.kwargs is not None
    response_format = fake_openai.completions.kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "Command_Payload"
    assert response_format["json_schema"]["strict"] is True
