from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.agent.graph.builder import run_agent_graph
from app.agent.tool_safety import AgentToolSafetyPolicy
from app.actions.builtin import register_builtin_actions
from app.core.tracker_store import InMemoryTrackerStore
from app.dialogue.llm_generator import LLMCommandGenerator
from app.core.exceptions import ForbiddenError
from app.entry.authorization import AuthorizedContext
from app.entry.models import EntryTask, Principal
from app.memory import MemoryEntityExtractor, QueryRewriter
from app.memory import ConversationMemoryService
from app.rag.answerer import KnowledgeAnswerer
from app.tickets import TicketService
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
        *,
        principal: Principal,
    ) -> list[dict[str, Any]]:
        authorization = AuthorizedContext.from_principal(principal)
        if str(sender_id or "").strip() != authorization.owner_user_id:
            raise ForbiddenError("permission denied")
        text = message.strip()
        return self._handle_normalized_message(
            text=text,
            sender_id=authorization.owner_user_id,
            conversation_id=conversation_id or sender_id,
            task=None,
            authorization=authorization,
        )

    def handle_task(self, task: EntryTask) -> list[dict[str, Any]]:
        if task.metadata.get("security_degraded") is True:
            return [
                {
                    "recipient_id": task.sender_id,
                    "text": "Request needs manual review before any tool action can run. Please rephrase the request.",
                    "metadata": {
                        "route": "clarify",
                        "entry_security_degraded": True,
                        "security_flags": task.security_flags.model_dump(mode="json", exclude_none=True),
                    },
                }
            ]

        authorization = AuthorizedContext.from_principal(task.principal)
        if task.sender_id != authorization.owner_user_id:
            raise ForbiddenError("permission denied")
        return self._handle_normalized_message(
            text=task.normalized_text,
            sender_id=task.sender_id,
            conversation_id=task.conversation_id,
            task=task,
            authorization=authorization,
        )

    def _handle_normalized_message(
        self,
        *,
        text: str,
        sender_id: str,
        conversation_id: str,
        task: EntryTask | None,
        authorization: AuthorizedContext,
    ) -> list[dict[str, Any]]:
        logger.info("agent.start sender_id=%s message_len=%d", sender_id, len(text))
        try:
            tracker = self.tracker_store.get_or_create(authorization)
            entry_metadata = _entry_metadata(task)
            state = {
                "sender_id": sender_id,
                "message": text,
                "tracker": tracker,
                "tracker_store": self.tracker_store,
                "authorization": authorization,
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
                "metadata": entry_metadata,
                "conversation_id": conversation_id,
                "memory_service": self.memory_service,
                **_entry_state(task),
            }
            result_state = run_agent_graph(state)
            responses = result_state.get("responses") or []
            return list(responses)
        finally:
            logger.info("agent.done sender_id=%s", sender_id)


def _entry_metadata(task: EntryTask | None) -> dict[str, Any]:
    if task is None:
        return {}
    return {
        "entry_trace_id": task.trace_id,
        "entry_request_id": task.request_id,
        "entry_source": task.source,
        "entry_scenario": task.scenario,
        "entry_capability": task.capability,
        "tenant_id": task.principal.tenant_id,
        "roles": list(task.principal.roles or []),
        "security_flags": task.security_flags.model_dump(mode="json", exclude_none=True),
        "text_hash": task.security_flags.text_hash,
    }


def _entry_state(task: EntryTask | None) -> dict[str, Any]:
    if task is None:
        return {}
    return {
        "entry_task": task,
        "principal": task.principal.model_dump(mode="json"),
        "tenant_id": task.principal.tenant_id,
        "roles": list(task.principal.roles or []),
        "data_scope": dict(task.principal.data_scope or {}),
        "security_flags": task.security_flags.model_dump(mode="json", exclude_none=True),
        "source": task.source,
        "scenario": task.scenario,
        "capability": task.capability,
    }
