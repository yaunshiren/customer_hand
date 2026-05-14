from __future__ import annotations

from typing import Any

from app.llm.client import LLMClient
from app.llm.prompts import CommandPromptBuilder
from app.dialogue.command_parser import CommandParser
from app.dialogue.command_processor import CommandProcessor


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
        system_prompt, user_prompt = self.prompt_builder.build(
            tracker=tracker,
            user_message=text,
            available_flows=self._build_available_flows(flow_ids),
        )
        llm_result = self.client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        raw = str(llm_result.get("raw_output") or "")

        if not llm_result.get("success") or not raw.strip():
            return {"handled": False, "reply_text": None, "results": [], "llm_result": llm_result}

        commands = self.command_parser.parse(raw)
        if not commands:
            return {"handled": False, "reply_text": None, "results": [], "llm_result": llm_result}

        results = self.command_processor.process(tracker, commands)
        reply_text = None
        for result in results:
            if (
                result.get("type") == "chitchat"
                and result.get("success") is True
                and result.get("data", {}).get("text")
            ):
                reply_text = result["data"]["text"]
                break

        return {
            "handled": True,
            "reply_text": reply_text,
            "results": results,
            "llm_result": llm_result,
        }

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
