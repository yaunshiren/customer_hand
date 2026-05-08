from __future__ import annotations

import os

from openai import OpenAI


class LLMCommandGenerator:
    def __init__(self) -> None:
        self.enabled = os.getenv("LLM_ENABLED", "false").lower() == "true"
        self.api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.model = os.getenv("QWEN_MODEL", "qwen-plus")

    def generate(self, prompt: str) -> str | None:
        if not self.enabled:
            return None

        if not self.api_key:
            return None

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你只能输出 JSON，不要输出任何解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )

        return resp.choices[0].message.content