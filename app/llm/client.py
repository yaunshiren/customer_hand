from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from app.utils.telemetry import emit_llm_event

logger = logging.getLogger(__name__)

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


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
        # timeout: float = 100.0,
        max_retries: int = 0,
        smoke_test_enabled: bool = False,
    ) -> None:
        self.enabled = enabled
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.smoke_test_enabled = smoke_test_enabled

    @classmethod
    def from_env(cls) -> "LLMClient":
        import os

        load_dotenv(DEFAULT_ENV_FILE)

        enabled = os.getenv("LLM_ENABLED", "false").lower() == "true"
        api_key = (
            os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("BAILIAN_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
        logger.info(
            "llm.env_check enabled=%s api_key=%s",
            enabled,
            cls._mask_api_key(api_key),
        )
        base_url = (
            os.getenv("DASHSCOPE_BASE_URL")
            or os.getenv("BAILIAN_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        model = os.getenv("QWEN_MODEL") or os.getenv("BAILIAN_MODEL") or "qwen-plus"
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
        timeout = float(os.getenv("LLM_TIMEOUT", "30"))
        max_retries = int(os.getenv("LLM_MAX_RETRIES", "0"))
        smoke_test_enabled = os.getenv("LLM_SMOKE_TEST_ENABLED", "false").lower() == "true"
        return cls(
            enabled=enabled,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            timeout=timeout,
            max_retries=max_retries,
            smoke_test_enabled=smoke_test_enabled,
        )

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> dict[str, Any]:
        start_time = time.perf_counter()

        if not self.enabled:
            result = self._build_result(
                success=False,
                raw_output="",
                latency_ms=self._latency_ms(start_time),
                error="LLM disabled",
            )
            emit_llm_event(
                "completion",
                model=self.model,
                success=False,
                latency_ms=result["latency_ms"],
                error="LLM disabled",
            )
            return result

        try:
            if self.smoke_test_enabled:
                self._direct_httpx_smoke_test()
            client = self._build_client()
            emit_llm_event(
                "request",
                model=self.model,
                system_len=len(system_prompt),
                user_len=len(user_prompt),
            )
            request_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": self.temperature if temperature is None else temperature,
                "timeout": self.timeout,
            }
            if top_p is not None:
                request_kwargs["top_p"] = top_p
            response = client.chat.completions.create(**request_kwargs)
            raw_output = response.choices[0].message.content or ""
            result = self._build_result(
                success=True,
                raw_output=raw_output,
                usage=self._record_usage(response),
                latency_ms=self._latency_ms(start_time),
                error=None,
            )
            emit_llm_event(
                "completion",
                model=self.model,
                success=True,
                latency_ms=result["latency_ms"],
                usage=result["usage"],
            )
            return result
        except Exception as exc:
            result = self._build_result(
                success=False,
                raw_output="",
                latency_ms=self._latency_ms(start_time),
                error=self._format_error(exc),
            )
            emit_llm_event(
                "completion",
                model=self.model,
                success=False,
                latency_ms=result["latency_ms"],
                error=result.get("error"),
            )
            return result

    def _build_client(self) -> OpenAI:
        if not self.api_key:
            raise ValueError("Missing DASHSCOPE_API_KEY or BAILIAN_API_KEY")
        logger.info(
            "llm.client_config model=%s base_url=%s api_key=%s",
            self.model,
            self.base_url,
            self._mask_api_key(self.api_key),
        )
        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=max(0, self.max_retries),
        )

    def _direct_httpx_smoke_test(self) -> None:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "smoke test"},
                {"role": "user", "content": "ping"},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
            logger.info("llm.httpx_smoke status=%s", response.status_code)
        except Exception as exc:
            logger.info("llm.httpx_smoke_failed error=%s", self._format_error(exc))

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

    @staticmethod
    def _mask_api_key(api_key: str, *, head: int = 5, tail: int = 5) -> str:
        if not api_key:
            return ""
        if len(api_key) <= head + tail:
            return "*" * len(api_key)
        return f"{api_key[:head]}...{api_key[-tail:]}"

    def _format_error(self, exc: Exception) -> str:
        message = str(exc)
        if self.api_key:
            message = message.replace(self.api_key, "***")
        return message or exc.__class__.__name__
