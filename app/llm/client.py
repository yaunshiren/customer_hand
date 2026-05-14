from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


@dataclass
class LLMResult:
    success: bool
    raw_output: str
    usage: dict[str, int]
    latency_ms: int
    model: str
    error: str | None = None


class LLMClient:
    def __init__(
        self,
        *,
        enabled: bool,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        timeout: float = 30.0,
    ) -> None:
        load_dotenv()
        self.enabled = enabled
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "LLMClient":
        import os

        enabled = os.getenv("LLM_ENABLED", "false").lower() == "true"
        api_key = (
            os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("BAILIAN_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
        base_url = (
            os.getenv("DASHSCOPE_BASE_URL")
            or os.getenv("BAILIAN_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        model = os.getenv("QWEN_MODEL") or os.getenv("BAILIAN_MODEL") or "qwen-plus"
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
        timeout = float(os.getenv("LLM_TIMEOUT", "30"))
        return cls(
            enabled=enabled,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            timeout=timeout,
        )

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        start_time = time.perf_counter()

        if not self.enabled:
            return self._build_result(
                success=False,
                raw_output="",
                latency_ms=self._latency_ms(start_time),
                error="LLM disabled",
            )

        try:
            client = self._build_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                timeout=self.timeout,
            )
            raw_output = response.choices[0].message.content or ""
            return self._build_result(
                success=True,
                raw_output=raw_output,
                usage=self._record_usage(response),
                latency_ms=self._latency_ms(start_time),
                error=None,
            )
        except Exception as exc:
            return self._build_result(
                success=False,
                raw_output="",
                latency_ms=self._latency_ms(start_time),
                error=self._format_error(exc),
            )

    def _build_client(self) -> OpenAI:
        if not self.api_key:
            raise ValueError("Missing DASHSCOPE_API_KEY or BAILIAN_API_KEY")
        return OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _record_usage(self, response: Any) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return self._empty_usage()
        return {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }

    def _build_result(
        self,
        *,
        success: bool,
        raw_output: str,
        latency_ms: int,
        error: str | None,
        usage: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        return {
            "success": success,
            "raw_output": raw_output,
            "usage": usage or self._empty_usage(),
            "latency_ms": latency_ms,
            "model": self.model,
            "error": error,
        }

    def _empty_usage(self) -> dict[str, int]:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _latency_ms(self, start_time: float) -> int:
        return int((time.perf_counter() - start_time) * 1000)

    def _format_error(self, exc: Exception) -> str:
        message = str(exc)
        if self.api_key:
            message = message.replace(self.api_key, "***")
        return message or exc.__class__.__name__
