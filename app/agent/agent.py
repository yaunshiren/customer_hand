from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.actions.builtin import register_builtin_actions
from app.agent.graph.builder import run_agent_graph
from app.agent.tool_safety import AgentToolSafetyPolicy
from app.core.tracker_store import InMemoryTrackerStore
from app.dialogue.llm_generator import LLMCommandGenerator
from app.memory import MemoryEntityExtractor, QueryRewriter
from app.rag.answerer import KnowledgeAnswerer
from app.tickets import TicketService
from app.memory import ConversationMemoryService
from app.settings import settings

logger = logging.getLogger(__name__)


class Agent:
    def __init__(
        self,
        tracker_store: InMemoryTrackerStore,
        flows: dict[str, Any] | None = None,
        knowledge_dir: Path | None = None,
        ticket_service: TicketService | None = None,
        tool_safety_policy: AgentToolSafetyPolicy | None = None,
    ) -> None:
        register_builtin_actions()
        self.tracker_store = tracker_store
        self.flows = flows or {}
        self.llm_generator = LLMCommandGenerator()
        self.knowledge_answerer = KnowledgeAnswerer(docs_dir=knowledge_dir)
        self.memory_entity_extractor = MemoryEntityExtractor.from_knowledge_dir(knowledge_dir)
        self.query_rewriter = QueryRewriter()
        self.ticket_service = ticket_service or TicketService()
        self.business_tool_service = None
        self.tool_safety_policy = tool_safety_policy or AgentToolSafetyPolicy()
        self.intent_classifier = None
        self.intent_route_policy = None
        self.business_classifier = None
        self.memory_service = ConversationMemoryService() if settings.trace_db_url else None

    def handle_message(
            self,
            message: str,
            sender_id: str,
            conversation_id: str | None = None,
        ) -> list[dict[str, Any]]:
        text = message.strip()
        logger.info("agent.start sender_id=%s message_len=%d", sender_id, len(text))
        try:
            tracker = self.tracker_store.get_or_create(sender_id)
            state = {
                "sender_id": sender_id,
                "message": text,
                "tracker": tracker,
                "tracker_store": self.tracker_store,
                "flows": self.flows,
                "llm_generator": self.llm_generator,
                "knowledge_answerer": self.knowledge_answerer,
                "memory_entity_extractor": self.memory_entity_extractor,
                "query_rewriter": self.query_rewriter,
                "ticket_service": self.ticket_service,
                "business_tool_service": self.business_tool_service,
                "tool_safety_policy": self.tool_safety_policy,
                "intent_classifier": self.intent_classifier,
                "intent_route_policy": self.intent_route_policy,
                "business_classifier": self.business_classifier,
                "metadata": {},
                "conversation_id": conversation_id or sender_id,
                "memory_service": self.memory_service,
            }
            result_state = run_agent_graph(state)
            responses = result_state.get("responses") or []
            return list(responses)
        finally:
            logger.info("agent.done sender_id=%s", sender_id)
