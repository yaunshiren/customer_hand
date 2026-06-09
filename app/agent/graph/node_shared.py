from __future__ import annotations

import re
import time
from typing import Any


def _has_command_type(results: list[dict[str, Any]], command_type: str) -> bool:
    return any(isinstance(result, dict) and result.get("type") == command_type for result in results)


def _first_command_data(results: list[dict[str, Any]], command_type: str) -> dict[str, Any]:
    for result in results:
        if isinstance(result, dict) and result.get("type") == command_type:
            data = result.get("data")
            if isinstance(data, dict):
                return data
    return {}


def _is_likely_order_id(value: str) -> bool:
    text = value.strip()
    if len(text) < 4 or len(text) > 64:
        return False
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", text):
        return False
    return any(ch.isdigit() for ch in text)


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))
