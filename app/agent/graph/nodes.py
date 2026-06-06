from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agent.graph.state import AgentState
from app.core.tracker import DialogueStateTracker
from app.dialogue.llm_generator import LLMCommandGenerator
from app.dialogue.command_processor import CommandProcessor
from app.dialogue.command_parser import CommandParser
from app.rag.answerer import KnowledgeAnswerer
from app.actions.registry import get_action
from app.actions.base import ActionResult
from app.intent import IntentClassifier, IntentRoutePolicy, IntentTaxonomy
from app.rag.citation import CitationBuilder
from app.tickets import TicketService
from app.actions.builtin import register_builtin_actions

logger = logging.getLogger(__name__)

DEFAULT_INTENT_TAXONOMY_PATH = Path(__file__).resolve().parents[3] / "data" / "intents" / "customer_intents.yml"


class _DisabledIntentLLMClient:
    enabled = False


@lru_cache(maxsize=1)
def _load_default_intent_taxonomy() -> IntentTaxonomy:
    return IntentTaxonomy.load(DEFAULT_INTENT_TAXONOMY_PATH)


def _normalize_tracker(tracker: Any, sender_id: str) -> DialogueStateTracker:
    if isinstance(tracker, DialogueStateTracker):
        return tracker
    if isinstance(tracker, dict):
        return DialogueStateTracker.from_dict(tracker)
    return DialogueStateTracker(sender_id=sender_id)


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


def _clear_started_flow(tracker: Any) -> None:
    if tracker is None:
        return

    active_flow = getattr(tracker, "active_flow", None)
    flow_history = getattr(tracker, "flow_history", None)
    if active_flow and isinstance(flow_history, list):
        flow_history.append(
            {
                "flow_name": active_flow,
                "status": "cancelled",
                "reason": "route_policy_override",
            }
        )

    if hasattr(tracker, "active_flow"):
        tracker.active_flow = None
        tracker.flow_status = "idle"
        tracker.flow_step_index = 0
        tracker.slot_to_collect = None
    elif isinstance(tracker, dict):
        tracker["active_flow"] = None
        tracker["flow_status"] = "idle"
        tracker["flow_step_index"] = 0
        tracker["slot_to_collect"] = None


def _graph_route_from_execution(execution_route: str) -> str:
    if execution_route == "tool":
        return "action"
    return execution_route


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _intent_response_metadata(intent_result: Any, route_decision: Any) -> dict[str, Any]:
    intent_data = _model_dump(intent_result)
    decision_data = _model_dump(route_decision)

    metadata: dict[str, Any] = {}
    intent_id = str(intent_data.get("intent_id") or "").strip()
    if intent_id and intent_id != "UNKNOWN":
        metadata["intentLeafIds"] = [intent_id]
    elif intent_data:
        metadata["intentLeafIds"] = []

    if intent_data:
        metadata["intentSource"] = intent_data.get("source") or "unknown"
        metadata["intentConfidence"] = intent_data.get("confidence")

    if decision_data:
        metadata["execution_route"] = decision_data.get("execution_route")
        metadata["system_route"] = decision_data.get("system_route")
        metadata["route_reason"] = decision_data.get("reason")
        metadata["requires_rag"] = decision_data.get("requires_rag")

    return metadata


def _policy_chitchat_reply(route_decision: Any) -> str:
    decision_data = _model_dump(route_decision)
    if decision_data.get("system_route") == "out_of_scope":
        return "抱歉，我主要处理比特严选的商品、订单、物流和售后问题，这类问题暂时无法回答。"
    return "您好！我是智能客服，请问有什么可以帮您？"


def _classify_intent(state: AgentState, message: str) -> Any | None:
    if not message:
        return None
    try:
        return _build_intent_classifier(state).classify(message)
    except Exception as exc:
        logger.exception("intent classify failed: %s", exc)
        return None


def _finish_active_flow(tracker: Any) -> None:
    active_flow = getattr(tracker, "active_flow", None)
    if not active_flow:
        return

    flow_history = getattr(tracker, "flow_history", None)
    if isinstance(flow_history, list):
        flow_history.append(
            {
                "flow_name": active_flow,
                "status": "finished",
            }
        )
    tracker.active_flow = None
    tracker.flow_status = "idle"
    tracker.flow_step_index = 0
    tracker.slot_to_collect = None


def _rag_response_metadata(
    *,
    route_name: str,
    rewritten_query: str | None,
    rag_matches: list[dict[str, Any]],
    used_llm: bool,
    ticket: dict[str, Any],
) -> dict[str, Any]:
    citation_metadata = CitationBuilder().from_matches(rag_matches)

    metadata = {
        "route": route_name,
        "rag_match_count": len(rag_matches),
        "used_llm": used_llm,
        "ticket_id": ticket.get("ticket_id") if isinstance(ticket, dict) else None,
        **citation_metadata,
    }
    if rewritten_query:
        metadata["rewritten_query"] = rewritten_query
    return metadata


def _merge_response_metadata(responses: list[dict[str, Any]], common: dict[str, Any]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for response in responses:
        item = dict(response)
        metadata = dict(item.get("metadata") or {})
        item["metadata"] = {**metadata, **common}
        merged.append(item)
    return merged


def load_context(state: AgentState) -> AgentState:
    sender_id = str(state.get("sender_id") or "default")
    message = str(state.get("message") or "").strip()
    tracker = _normalize_tracker(state.get("tracker"), sender_id)

    tracker.update_with_user_message(message)

    return {
        **state,
        "sender_id": sender_id,
        "message": message,
        "tracker": tracker,
    }


def understand(state: AgentState) -> AgentState:
    sender_id = str(state.get("sender_id") or "default")
    message = str(state.get("message") or "").strip()
    tracker = state.get("tracker")
    llm_generator = state.get("llm_generator")

    if llm_generator is None or not hasattr(llm_generator, "generate"):
        llm_generator = LLMCommandGenerator()

    state = {
        **state,
        "llm_generator": llm_generator,
    }
    intent_result = _classify_intent(state, message)

    flow_ids = sorted((state.get("flows") or {}).keys()) if isinstance(state.get("flows"), dict) else []

    command_processor = state.get("command_processor")
    if command_processor is None or not hasattr(command_processor, "process"):
        command_processor = CommandProcessor()
    command_parser = state.get("command_parser")
    if command_parser is None or not hasattr(command_parser, "parse"):
        command_parser = CommandParser()

    try:
        llm_result = llm_generator.generate(tracker, message, flow_ids=flow_ids)
    except Exception as exc:
        logger.exception("understand node failed: %s", exc)
        return {
            **state,
            "sender_id": sender_id,
            "message": message,
            "error": str(exc),
            "intent_result": intent_result,
            "llm_result": {"handled": False, "reply_text": None, "results": []},
            "llm_results": [],
        }

    results = llm_result.get("results") or []
    if not results:
        raw = str(llm_result.get("raw_output") or "").strip()
        parsed_commands = command_parser.parse(raw)
        if parsed_commands:
            results = command_processor.process(tracker, parsed_commands)
        else:
            reply_text = llm_result.get("reply_text")
            if reply_text:
                results = [{"type": "chitchat", "success": True, "data": {"text": reply_text}}]

    command_types = [result.get("type") for result in results if isinstance(result, dict)]
    if _has_command_type(results, "start_flow") and tracker is not None:
        for result in results:
            if isinstance(result, dict) and result.get("type") == "start_flow":
                data = result.get("data") or {}
                flow_id = str(data.get("flow_id") or data.get("flow") or "").strip()
                if flow_id:
                    tracker.active_flow = flow_id
                    tracker.flow_status = "running"
                    tracker.flow_step_index = 0
                    tracker.slot_to_collect = None
                break

    return {
        **state,
        "sender_id": sender_id,
        "message": message,
        "intent_result": intent_result,
        "llm_result": llm_result,
        "llm_results": results,
        "handled": bool(llm_result.get("handled")),
        "reply_text": llm_result.get("reply_text"),
        "command_types": command_types,
    }


def route(state: AgentState) -> AgentState:
    llm_result = state.get("llm_result") or {}
    results = state.get("llm_results") or []
    reply_text = str(state.get("reply_text") or "").strip()
    message = str(state.get("message") or "").strip()
    tracker = state.get("tracker")
    active_flow = getattr(tracker, "active_flow", None) if tracker is not None else None
    llm_generator = state.get("llm_generator")
    llm_enabled = bool(getattr(llm_generator, "enabled", False)) if llm_generator is not None else False
    intent_result: Any | None = state.get("intent_result")
    route_decision: Any | None = None

    if intent_result is not None:
        try:
            route_decision = _build_intent_route_policy(state).decide(intent_result, message, tracker)
        except Exception as exc:
            logger.exception("intent route policy failed: %s", exc)
            route_decision = None

    if (
        route_decision is not None
        and intent_result is not None
        and getattr(intent_result, "intent_id", None) != "UNKNOWN"
        and not _has_command_type(results, "set_slot")
    ):
        route_name = _graph_route_from_execution(str(route_decision.execution_route))
        if route_name != "flow" and _has_command_type(results, "start_flow"):
            _clear_started_flow(tracker)
    elif _has_command_type(results, "ticket"):
        route_name = "ticket"
    elif _has_command_type(results, "knowledge_answer"):
        route_name = "rag"
    elif _has_command_type(results, "chitchat") and reply_text:
        route_name = "chitchat"
    elif _has_command_type(results, "start_flow") or active_flow:
        route_name = "flow"
    elif reply_text:
        route_name = "chitchat"
    elif bool(llm_result.get("handled")):
        route_name = "action"
    elif not llm_enabled and any(keyword in message for keyword in ("退货", "售后", "退款", "不想要", "物流", "快递", "配送")):
        route_name = "flow"
    elif message:
        route_name = "fallback"
    else:
        route_name = "fallback"

    if route_decision is not None and route_name == "chitchat" and not reply_text:
        reply_text = _policy_chitchat_reply(route_decision)

    return {
        **state,
        "route": route_name,
        "reply_text": reply_text,
        "intent_result": _model_dump(intent_result),
        "route_decision": _model_dump(route_decision),
    }


def rag(state: AgentState) -> AgentState:
    results = state.get("llm_results") or []
    message = str(state.get("message") or "").strip()
    knowledge_answerer = state.get("knowledge_answerer")

    if not isinstance(knowledge_answerer, KnowledgeAnswerer):
        knowledge_answerer = KnowledgeAnswerer()

    command_data = _first_command_data(results, "knowledge_answer")
    rag_query = str(command_data.get("query") or message)
    top_k = int(command_data.get("top_k") or 3)
    intent_data = _model_dump(state.get("intent_result"))
    intent_id = str(intent_data.get("intent_id") or "").strip()
    if intent_id == "UNKNOWN":
        intent_id = ""

    try:
        answer = knowledge_answerer.answer(rag_query, top_k=top_k, intent_id=intent_id or None)
    except Exception as exc:
        logger.exception("rag node failed: %s", exc)
        return {
            **state,
            "error": str(exc),
            "route": "fallback",
            "rag_query": rag_query,
            "rag_matches": [],
            "knowledge_answer": "",
            "used_llm": False,
        }

    return {
        **state,
        "rag_query": rag_query,
        "rag_matches": answer.get("matches", []),
        "knowledge_answer": str(answer.get("answer") or ""),
        "used_llm": bool(answer.get("used_llm")),
    }


def flow(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    message = str(state.get("message") or "").strip()
    flow_result: dict[str, Any] = {}

    if tracker is None:
        return {
            **state,
            "route": "fallback",
            "flow_result": {"next_action": "action_default_fallback", "reason": "missing_tracker"},
            "next_action": "action_default_fallback",
        }

    active_flow = getattr(tracker, "active_flow", None)
    slot_to_collect = getattr(tracker, "slot_to_collect", None)

    if slot_to_collect is not None and active_flow is not None:
        if slot_to_collect == "order_id" and not _is_likely_order_id(message):
            flow_result["ignored_slot"] = slot_to_collect
            flow_result["reason"] = "invalid_slot_value"
        else:
            tracker.set_slot(slot_to_collect, message)
            tracker.slot_to_collect = None
            flow_result["collected_slot"] = slot_to_collect

    next_action = "action_default_fallback"
    active_flow = getattr(tracker, "active_flow", None)
    if not active_flow:
        flow_result["reason"] = "no_active_flow"
    elif active_flow in ("postsale", "apply_postsale"):
        next_action = "action_confirm_postsale" if tracker.get_slot("order_id") else "action_ask_order_id"
    elif active_flow in ("logistics", "query_logistics"):
        next_action = "action_show_logistics" if tracker.get_slot("order_id") else "action_ask_order_id"
    else:
        flow_def = (state.get("flows") or {}).get(active_flow) if isinstance(state.get("flows"), dict) else None
        if flow_def is None:
            next_action = "action_default_fallback"
        else:
            flow_result["flow_def"] = flow_def
            next_action = "action_default_fallback"

    if next_action == "action_ask_order_id":
        tracker.slot_to_collect = "order_id"
        tracker.flow_status = "waiting_input"
    elif next_action != "action_default_fallback":
        tracker.flow_status = "running"

    flow_result["next_action"] = next_action
    flow_result["active_flow"] = active_flow
    flow_result["slot_to_collect"] = getattr(tracker, "slot_to_collect", None)

    return {
        **state,
        "flow_result": flow_result,
        "next_action": next_action,
    }


def action(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    next_action = str(state.get("next_action") or "action_default_fallback")
    metadata = dict(state.get("metadata") or {})

    register_builtin_actions()
    action_obj = get_action(next_action)
    if action_obj is None:
        next_action = "action_default_fallback"
        action_obj = get_action(next_action)

    if action_obj is None or tracker is None:
        result = ActionResult(text="系统暂时不可用。", metadata={"action": next_action, "error": "action_not_found"})
        return {
            **state,
            "action_result": result.to_dict(),
            "responses": [{"text": result.text or "", "metadata": result.metadata}],
        }

    try:
        result = action_obj.run(tracker, **metadata)
    except Exception as exc:
        logger.exception("action node failed: %s", exc)
        result = ActionResult(
            text="系统暂时不可用。",
            metadata={"action": next_action, "error": str(exc)},
        )
        return {
            **state,
            "error": str(exc),
            "action_result": result.to_dict(),
            "responses": [{"text": result.text or "", "metadata": result.metadata}],
        }

    if next_action in {"action_confirm_postsale", "action_show_logistics"}:
        _finish_active_flow(tracker)

    return {
        **state,
        "action_result": result.to_dict(),
        "responses": [{"text": result.text or "", "metadata": result.metadata}],
    }


def ticket(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    sender_id = str(state.get("sender_id") or "default")
    message = str(state.get("message") or "").strip()
    llm_results = state.get("llm_results") or []
    ticket_service = state.get("ticket_service")

    if not isinstance(ticket_service, TicketService):
        ticket_service = TicketService()

    ticket_data = _first_command_data(llm_results, "ticket")
    ticket_text = str(ticket_data.get("text") or message)
    ticket = ticket_service.create_ticket(
        sender_id=sender_id,
        text=ticket_text,
        metadata={"source": "ticket"},
        title=ticket_data.get("title"),
        summary=ticket_data.get("summary"),
        category=ticket_data.get("category"),
        priority=ticket_data.get("priority"),
        suggestion=ticket_data.get("suggestion"),
    )

    if tracker is not None:
        tracker.latest_action_name = "ticket_create"

    response_metadata = {
        "source": "ticket",
        "ticket_id": ticket.ticket_id,
        "category": ticket.category,
        "priority": ticket.priority,
    }

    return {
        **state,
        "ticket": {
            "ticket_id": ticket.ticket_id,
            "sender_id": ticket.sender_id,
            "title": ticket.title,
            "summary": ticket.summary,
            "category": ticket.category,
            "priority": ticket.priority,
            "suggestion": ticket.suggestion,
            "status": ticket.status,
            "metadata": ticket.metadata,
        },
        "responses": [
            {
                "recipient_id": sender_id,
                "text": "这个问题需要人工进一步确认，我已经帮你生成工单，客服会根据订单信息继续处理。",
                "metadata": response_metadata,
            }
        ],
        "route": "ticket",
    }


def generate_response(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    sender_id = str(state.get("sender_id") or "default")
    reply_text = str(state.get("reply_text") or "").strip()
    responses = list(state.get("responses") or [])
    action_result = state.get("action_result") or {}
    ticket = state.get("ticket") or {}
    route_name = str(state.get("route") or "fallback")
    rag_matches = state.get("rag_matches") or []
    knowledge_answer = str(state.get("knowledge_answer") or "")
    error = str(state.get("error") or "")
    common_metadata = _rag_response_metadata(
        route_name=route_name,
        rewritten_query=str(state.get("rag_query") or "").strip() or None,
        rag_matches=rag_matches,
        used_llm=bool(state.get("used_llm")),
        ticket=ticket if isinstance(ticket, dict) else {},
    )
    common_metadata.update(_intent_response_metadata(state.get("intent_result"), state.get("route_decision")))

    if reply_text and route_name == "chitchat":
        responses = [
            {
                "recipient_id": sender_id,
                "text": reply_text,
                "metadata": {"source": "llm", "command_type": "chitchat"},
            }
        ]

    if tracker is not None and responses:
        final_text = str(responses[0].get("text") or "")
        tracker.add_bot_message(final_text)
        tracker.latest_action_name = str(action_result.get("metadata", {}).get("action") or tracker.latest_action_name or route_name)

    final_responses = list(responses)
    if not final_responses:
        fallback_text = knowledge_answer or str(action_result.get("text") or "系统暂时不可用。")
        final_responses = [
            {
                "recipient_id": sender_id,
                "text": fallback_text,
                "metadata": {
                    "route": route_name,
                    "rag_match_count": len(rag_matches),
                    "error": error or None,
                    **(action_result.get("metadata") or {}),
                },
            }
        ]
        if tracker is not None:
            tracker.add_bot_message(fallback_text)

    final_responses = _merge_response_metadata(final_responses, common_metadata)

    return {
        **state,
        "responses": final_responses,
    }


def save_context(state: AgentState) -> AgentState:
    tracker = state.get("tracker")
    tracker_store = state.get("tracker_store")

    if tracker_store is not None and tracker is not None:
        tracker_store.save(tracker)

    return {
        **state,
        "saved": True,
    }
