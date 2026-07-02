from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.dialogue.command_parser import CommandParser
from app.dialogue.command_processor import CommandProcessor
from app.llm.client import LLMClient
from app.llm.prompts import CommandPromptBuilder
from app.utils.telemetry import emit_llm_event

DEFAULT_CHITCHAT_REPLY = "您好！我是智能客服，请问有什么可以帮您？"


class CommandGenerationPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    commands: list[dict[str, Any]] = Field(default_factory=list)


class LLMCommandGenerator:
    def __init__(self) -> None:
        self.client = LLMClient.from_env()
        self.prompt_builder = CommandPromptBuilder()
        self.command_parser = CommandParser()
        self.command_processor = CommandProcessor()

    @property
    def enabled(self) -> bool:
        return self.client.enabled

    def generate(self, tracker: Any, text: str, flow_ids: list[str] | None = None) -> dict[str, Any]:
        emit_llm_event("command_pipeline.start", user_len=len(text), flows=len(flow_ids or []))
        system_prompt, user_prompt = self.prompt_builder.build(
            tracker=tracker,
            user_message=text,
            available_flows=self._build_available_flows(flow_ids),
        )
        llm_result = self.client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format={"type": "json_object"},
            response_model=CommandGenerationPayload,
        )
        raw = str(llm_result.get("raw_output") or "")

        if not llm_result.get("success") or not raw.strip():
            emit_llm_event(
                "command_pipeline.end",
                handled=False,
                reason="llm_failed_or_empty",
                success=bool(llm_result.get("success")),
            )
            return {"handled": False, "reply_text": None, "results": [], "llm_result": llm_result}

        commands = self.command_parser.parse(raw)
        if not commands:
            emit_llm_event("command_pipeline.end", handled=False, reason="parse_empty", success=True)
            return {"handled": False, "reply_text": None, "results": [], "llm_result": llm_result}

        results = self.command_processor.process(tracker, commands)
        reply_text = self._extract_chitchat_reply(results)

        emit_llm_event(
            "command_pipeline.end",
            handled=True,
            command_count=len(results),
            has_chitchat_reply=reply_text is not None,
        )
        return {
            "handled": True,
            "reply_text": reply_text,
            "results": results,
            "llm_result": llm_result,
        }

    def _extract_chitchat_reply(self, results: list[dict[str, Any]]) -> str | None:
        for result in results:
            if result.get("type") != "chitchat" or result.get("success") is not True:
                continue
            text = str(result.get("data", {}).get("text") or "").strip()
            return text or DEFAULT_CHITCHAT_REPLY
        return None

    def _build_available_flows(self, flow_ids: list[str] | None) -> list[dict[str, Any]] | None:
        if not flow_ids:
            return None
        return [
            {
                "flow_id": flow_id,
                "description": "项目中加载的流程",
                "required_slots": [],
            }
            for flow_id in flow_ids
        ]
