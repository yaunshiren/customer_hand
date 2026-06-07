from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


PENDING_TOOL_CONFIRMATION_SLOT = "__pending_tool_confirmation__"


@dataclass(frozen=True)
class AgentToolSafetyPolicy:
    max_tool_calls_per_turn: int = 1
    tool_timeout_seconds: float = 3.0
    max_tool_retries: int = 1
    retry_backoff_seconds: float = 0.0
    duplicate_call_detection: bool = True
    confirmation_ttl_seconds: int = 600
    high_risk_levels: tuple[str, ...] = ("medium", "high")
    confirm_keywords: tuple[str, ...] = ("确认", "确定", "是", "是的", "可以", "同意", "继续", "执行")
    cancel_keywords: tuple[str, ...] = ("取消", "不要", "不用", "否", "不是", "先不", "停止")


def fingerprint_tool_call(tool_name: str, arguments: dict[str, Any]) -> str:
    payload = {
        "tool_name": str(tool_name or "").strip(),
        "arguments": arguments,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_confirmation_message(text: str, policy: AgentToolSafetyPolicy) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return _matches_keyword(normalized, policy.confirm_keywords)


def is_cancellation_message(text: str, policy: AgentToolSafetyPolicy) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return _matches_keyword(normalized, policy.cancel_keywords)


def _normalize_text(text: str) -> str:
    return str(text or "").strip().casefold().replace(" ", "")


def _matches_keyword(normalized_text: str, keywords: tuple[str, ...]) -> bool:
    for keyword in keywords:
        normalized_keyword = _normalize_text(keyword)
        if not normalized_keyword:
            continue
        if len(normalized_keyword) <= 1:
            if normalized_text == normalized_keyword:
                return True
        elif normalized_keyword in normalized_text:
            return True
    return False
