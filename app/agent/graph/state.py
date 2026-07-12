from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """Shared runtime state for the agent graph.

    This state keeps the request-scoped inputs and node outputs explicit,
    while the persistent conversation data remains inside ``tracker``.
    """

    # Request inputs.
    sender_id: str
    message: str
    entry_task: Any
    principal: dict[str, Any]
    tenant_id: str
    roles: list[str]
    data_scope: dict[str, Any]
    security_flags: dict[str, Any]
    source: str
    scenario: str
    capability: str

    # Persistent conversation context.
    tracker: Any
    tracker_store: Any
    authorization: Any

    # Runtime dependencies injected by Agent.
    flows: dict[str, Any]
    llm_generator: Any
    command_processor: Any
    command_parser: Any
    knowledge_answerer: Any
    memory_entity_extractor: Any
    query_rewriter: Any
    ticket_service: Any
    business_tool_service: Any
    tool_safety_policy: Any
    intent_classifier: Any
    intent_route_policy: Any
    business_classifier: Any

    # LLM understanding outputs.
    llm_result: dict[str, Any]
    llm_results: list[dict[str, Any]]
    handled: bool
    reply_text: str | None

    # Routing and intermediate node results.
    route: str
    intent_result: Any
    route_decision: Any
    business_classification: Any
    rag_query: str
    query_rewrite: dict[str, Any]
    rag_matches: list[dict[str, Any]]
    knowledge_answer: str
    used_llm: bool

    # Flow execution outputs.
    flow_name: str | None
    flow_result: dict[str, Any]
    next_action: str

    # Action / ticket outputs.
    action_result: dict[str, Any]
    tool_result: dict[str, Any]
    tool_safety: dict[str, Any]
    tool_call_count: int
    tool_call_fingerprints: list[str]
    confirmed_tool_call: dict[str, Any]
    ticket: dict[str, Any]

    # Final response and error propagation.
    responses: list[dict[str, Any]]
    error: str
    metadata: dict[str, Any]
    memory_extraction: dict[str, Any]


    # 对话id和记忆服务
    conversation_id: str | None
    memory_service: Any
