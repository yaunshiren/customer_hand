from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agent.graph.state import AgentState
from app.agent.tool_safety import AgentToolSafetyPolicy
from app.intent import BusinessQuestionClassifier, IntentClassifier, IntentRoutePolicy, IntentTaxonomy
from app.memory import MemoryEntityExtractor, QueryRewriter
from app.tools import MockBusinessToolService, ToolExecutionPolicy

logger = logging.getLogger(__name__)

DEFAULT_INTENT_TAXONOMY_PATH = Path(__file__).resolve().parents[3] / "data" / "intents" / "customer_intents.yml"


class _DisabledIntentLLMClient:
    enabled = False


def _load_default_intent_taxonomy() -> IntentTaxonomy:
    return IntentTaxonomy.load(DEFAULT_INTENT_TAXONOMY_PATH)


def _build_intent_classifier(state: AgentState) -> Any:
    classifier = state.get("intent_classifier")
    if classifier is not None and hasattr(classifier, "classify"):
        return classifier

    llm_generator = state.get("llm_generator")
    llm_client = getattr(llm_generator, "client", None) or _DisabledIntentLLMClient()
    return IntentClassifier(_load_default_intent_taxonomy(), llm_client=llm_client)


def _build_intent_route_policy(state: AgentState) -> Any:
    policy = state.get("intent_route_policy")
    if policy is not None and hasattr(policy, "decide"):
        return policy
    return IntentRoutePolicy()


def _build_business_question_classifier(state: AgentState) -> Any:
    classifier = state.get("business_classifier")
    if classifier is not None and hasattr(classifier, "classify"):
        return classifier
    return BusinessQuestionClassifier()


def _build_tool_safety_policy(state: AgentState) -> AgentToolSafetyPolicy:
    policy = state.get("tool_safety_policy")
    if isinstance(policy, AgentToolSafetyPolicy):
        return policy
    if isinstance(policy, dict):
        try:
            return AgentToolSafetyPolicy(**policy)
        except TypeError:
            logger.warning("invalid tool safety policy ignored")
    return AgentToolSafetyPolicy()


def _build_business_tool_service(state: AgentState) -> Any:
    service = state.get("business_tool_service")
    if service is not None:
        return service
    policy = _build_tool_safety_policy(state)
    return MockBusinessToolService(
        policy=ToolExecutionPolicy(
            timeout_seconds=policy.tool_timeout_seconds,
            max_retries=policy.max_tool_retries,
            retry_backoff_seconds=policy.retry_backoff_seconds,
        )
    )


def _build_memory_entity_extractor(state: AgentState) -> MemoryEntityExtractor:
    extractor = state.get("memory_entity_extractor")
    if isinstance(extractor, MemoryEntityExtractor):
        return extractor
    return MemoryEntityExtractor()


def _build_query_rewriter(state: AgentState) -> Any:
    rewriter = state.get("query_rewriter")
    if rewriter is not None and hasattr(rewriter, "rewrite"):
        return rewriter
    return QueryRewriter()
