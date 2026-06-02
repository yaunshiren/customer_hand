from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.intent import IntentCandidate, IntentResult


def test_intent_result_accepts_llm_classifier_source() -> None:
    result = IntentResult(
        intent_id="S16_物流配送",
        intent_name="物流配送",
        intent_type="KB_TOOL",
        confidence=0.86,
        candidates=[
            IntentCandidate(intent_id="S16_物流配送", confidence=0.86),
            IntentCandidate(intent_id="S15_退换货", confidence=0.42),
        ],
        reason="用户询问已发货后是否能改地址",
        source="llm_classifier",
    )

    assert result.intent_id == "S16_物流配送"
    assert result.intent_type == "KB_TOOL"
    assert result.source == "llm_classifier"
    assert len(result.candidates) == 2


def test_intent_result_defaults_to_unknown_source_and_empty_candidates() -> None:
    result = IntentResult(
        intent_id="UNKNOWN",
        intent_name="未知",
        intent_type="UNKNOWN",
        confidence=0.0,
    )

    assert result.source == "unknown"
    assert result.candidates == []


@pytest.mark.parametrize("source", ["llm_classifier", "rule_fallback", "unknown"])
def test_intent_result_supports_expected_sources(source: str) -> None:
    result = IntentResult(
        intent_id="F2_功能建议",
        intent_name="功能建议",
        intent_type="TICKET",
        confidence=0.9,
        source=source,
    )

    assert result.source == source


def test_intent_result_rejects_invalid_source() -> None:
    with pytest.raises(ValidationError):
        IntentResult(
            intent_id="F2_功能建议",
            intent_name="功能建议",
            intent_type="TICKET",
            confidence=0.9,
            source="keyword_router",
        )


def test_intent_confidence_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        IntentCandidate(intent_id="S1_选购推荐", confidence=1.1)
