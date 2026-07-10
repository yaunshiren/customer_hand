from __future__ import annotations

from collections.abc import Iterable

from .models import CaseEvaluationResult


BADCASE_PRIORITY = (
    "UNSAFE_ACTION",
    "CONTEXT_LOST",
    "INTENT_ERROR",
    "ROUTE_ERROR",
    "TOOL_SELECTION_ERROR",
    "TOOL_ARGUMENT_ERROR",
    "RAG_MISS",
    "ANSWER_UNGROUNDED",
)

CHECK_TO_BADCASE = {
    "safety": "UNSAFE_ACTION",
    "context": "CONTEXT_LOST",
    "intent": "INTENT_ERROR",
    "route": "ROUTE_ERROR",
    "tool_selection": "TOOL_SELECTION_ERROR",
    "tool_args_complete": "TOOL_ARGUMENT_ERROR",
    "rag_hit_at_3": "RAG_MISS",
    "grounding": "ANSWER_UNGROUNDED",
}


def classify_badcases(
    results: Iterable[CaseEvaluationResult],
) -> list[CaseEvaluationResult]:
    classified: list[CaseEvaluationResult] = []
    priority = {name: index for index, name in enumerate(BADCASE_PRIORITY)}
    for result in results:
        error_types = [
            error_type
            for check_name, error_type in CHECK_TO_BADCASE.items()
            if check_name in result.checks
            and result.checks[check_name].applicable
            and result.checks[check_name].passed is False
        ]
        ordered = sorted(set(error_types), key=lambda name: priority[name])
        result.error_types = ordered
        result.error_type = ordered[0] if ordered else None
        classified.append(result)
    return classified

