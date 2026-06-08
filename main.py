from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.agent.agent import Agent
from app.api.errors import register_exception_handlers
from app.api.schemas import MessageRequest, MessageResponse
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.flow_loader import FlowLoader
from app.core.logging import configure_logging
from app.core.trace import new_trace_id, run_with_trace, trace_id_from_request, trace_scope
from app.core.tracker_store import InMemoryTrackerStore
from app.persistence.trace_recorder import AgentTraceRecorder
from app.rag.citation import CitationBuilder
from app.rag.reindex import get_index_status, rebuild_index
from app.rag.retriever import KnowledgeBaseRetriever, normalize_rag_backend
from app.settings import settings

logger = logging.getLogger(__name__)

SERVICE_NAME = settings.app_name
VERSION = settings.app_version
BASE_DIR = Path(__file__).resolve().parent
INSPECT_TEMPLATE = BASE_DIR / "app" / "api" / "templates" / "inspect.html"


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _conversation_id(sender_id: str) -> str:
    text = str(sender_id).strip()
    return text or "default"


def _response_metadata(responses: list[MessageResponse]) -> dict[str, Any]:
    if not responses:
        return {}
    return dict(responses[0].metadata or {})


def _memory_snapshot(metadata: dict[str, Any]) -> dict[str, Any] | None:
    value = metadata.get("memory_snapshot")
    snapshot = dict(value) if isinstance(value, dict) else None
    query_rewrite = metadata.get("query_rewrite")
    if isinstance(query_rewrite, dict):
        snapshot = snapshot or {}
        snapshot["query_rewrite"] = dict(query_rewrite)
    return snapshot


def _final_answer(responses: list[MessageResponse]) -> str | None:
    texts = [str(item.text).strip() for item in responses if item.text and str(item.text).strip()]
    if not texts:
        return None
    return "\n".join(texts)


def _first_intent_id(metadata: dict[str, Any]) -> str | None:
    value = metadata.get("intentLeafIds")
    if isinstance(value, list) and value:
        text = str(value[0]).strip()
        return text or None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    logger.info("service.start name=%s version=%s", SERVICE_NAME, VERSION)
    yield
    logger.info("service.stop name=%s", SERVICE_NAME)


def create_app() -> FastAPI:
    store = InMemoryTrackerStore(memory_turn_limit=settings.memory_recent_turn_limit)
    flows = FlowLoader().load_directory(settings.flow_dir)
    agent = Agent(tracker_store=store, flows=flows, knowledge_dir=settings.knowledge_dir)
    trace_recorder = AgentTraceRecorder()

    app = FastAPI(title=SERVICE_NAME, version=VERSION, lifespan=app_lifespan)
    app.state.agent = agent
    app.state.kb_retriever = agent.knowledge_answerer.retriever
    app.state.trace_recorder = trace_recorder
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    @app.middleware("http")
    async def trace_header_middleware(request: Request, call_next):
        incoming = request.headers.get("x-trace-id") or request.headers.get("x-request-id")
        tid = (incoming or "").strip() or new_trace_id()
        request.state.trace_id = tid
        response = await call_next(request)
        response.headers["X-Trace-Id"] = str(getattr(request.state, "trace_id", tid))
        return response

    @app.get("/health")
    async def health(request: Request):
        with trace_scope(trace_id_from_request(request)):
            return {
                "status": "ok",
                "service": SERVICE_NAME,
                "version": VERSION,
            }

    @app.get("/inspect", response_class=FileResponse)
    async def inspect_page(request: Request) -> FileResponse:
        with trace_scope(trace_id_from_request(request)):
            if not INSPECT_TEMPLATE.exists():
                raise NotFoundError("inspect template not found")

            return FileResponse(INSPECT_TEMPLATE)

    @app.post("/api/messages", response_model=list[MessageResponse])
    async def send_message(req: MessageRequest, request: Request) -> list[MessageResponse]:
        trace_id = trace_id_from_request(request)
        started_at = time.perf_counter()
        conversation_id = _conversation_id(req.sender_id)
        trace_recorder: AgentTraceRecorder = request.app.state.trace_recorder
        error_recorded = False

        with trace_scope(trace_id):
            text = req.message.strip()
            if not text:
                trace_recorder.record_message_error(
                    trace_id=trace_id,
                    sender_id=req.sender_id,
                    conversation_id=conversation_id,
                    user_text=req.message or "<empty_message>",
                    error="message must not be empty",
                    latency_ms=_elapsed_ms(started_at),
                    route="bad_request",
                )
                error_recorded = True
                raise BadRequestError("message must not be empty")

            logger.info(
                "api.messages sender_id=%s message_len=%d",
                req.sender_id,
                len(text),
            )
            trace_recorder.record_message_start(
                trace_id=trace_id,
                sender_id=req.sender_id,
                conversation_id=conversation_id,
                user_text=text,
            )

            try:
                def handle() -> list[dict[str, object]]:
                    return request.app.state.agent.handle_message(
                        message=req.message,
                        sender_id=req.sender_id,
                    )

                raw_responses = await run_with_trace(request, handle)
                now = datetime.now(timezone.utc).isoformat()

                responses: list[MessageResponse] = []
                for item in raw_responses:
                    responses.append(
                        MessageResponse(
                            recipient_id=str(item.get("recipient_id", req.sender_id)),
                            text=item.get("text"),
                            timestamp=str(item.get("timestamp") or now),
                            metadata=dict(item.get("metadata") or {}),
                        )
                    )

                metadata = _response_metadata(responses)
                trace_recorder.record_message_success(
                    trace_id=trace_id,
                    sender_id=req.sender_id,
                    conversation_id=conversation_id,
                    user_text=text,
                    rewritten_query=metadata.get("rewritten_query") or None,
                    memory_snapshot=_memory_snapshot(metadata),
                    intent_id=_first_intent_id(metadata),
                    intent_confidence=_optional_float(metadata.get("intentConfidence")),
                    route=str(metadata.get("route") or "").strip() or None,
                    final_answer=_final_answer(responses),
                    latency_ms=_elapsed_ms(started_at),
                )

                logger.info("api.messages.done sender_id=%s replies=%d", req.sender_id, len(responses))
                return responses
            except Exception as exc:
                if not error_recorded:
                    trace_recorder.record_message_error(
                        trace_id=trace_id,
                        sender_id=req.sender_id,
                        conversation_id=conversation_id,
                        user_text=text,
                        error=exc,
                        latency_ms=_elapsed_ms(started_at),
                    )
                raise

    @app.get("/api/eval/rag")
    async def eval_rag(request: Request, question: str, top_k: int = 5):
        with trace_scope(trace_id_from_request(request)):
            text = question.strip()
            if not text:
                raise BadRequestError("question must not be empty")

            effective_top_k = max(1, min(int(top_k), 20))
            trace_id = trace_id_from_request(request)

            retriever = request.app.state.kb_retriever
            retrieval = await run_with_trace(request, lambda: retriever.retrieve(text, top_k=effective_top_k))
            matches = retrieval.matches or []
            citation_metadata = CitationBuilder().from_matches(matches)

            return {
                "success": True,
                "data": {
                    "question": text,
                    "retrievedDocIds": citation_metadata["rag_doc_ids"],
                    "retrievedChunkIds": citation_metadata["rag_chunk_ids"],
                    "retrievedContexts": citation_metadata["retrieved_contexts"],
                    "retrievedContextDocIds": citation_metadata["rag_context_doc_ids"],
                    "intentLeafIds": [],
                    "intentSource": "not_exposed",
                    "hasKb": bool(matches),
                    "hasMcp": False,
                    "traceId": trace_id,
                },
            }

    @app.get("/api/tracker/{sender_id}/full")
    async def get_tracker_full(request: Request, sender_id: str):
        with trace_scope(trace_id_from_request(request)):
            tracker = store.retrieve(sender_id)
            if tracker is None:
                raise NotFoundError("tracker not found")

            return {
                "sender_id": sender_id,
                "exists": True,
                "tracker": tracker,
            }

    @app.post("/api/tracker/{sender_id}/reset")
    async def reset_tracker(request: Request, sender_id: str):
        with trace_scope(trace_id_from_request(request)):
            deleted = store.delete(sender_id)
            return {
                "sender_id": sender_id,
                "reset": deleted,
                "message": (
                    "Tracker reset successfully"
                    if deleted
                    else "Tracker did not exist"
                ),
            }

    @app.get("/api/knowledge/status")
    async def knowledge_status(request: Request):
        with trace_scope(trace_id_from_request(request)):
            status = get_index_status()
            status["rag_backend"] = settings.rag_backend
            return status

    @app.post("/api/knowledge/reindex")
    async def knowledge_reindex(request: Request):
        with trace_scope(trace_id_from_request(request)):
            if normalize_rag_backend(settings.rag_backend) != "chroma":
                raise BadRequestError(
                    "RAG_BACKEND must be chroma to rebuild vector index. "
                    "Set RAG_BACKEND=chroma in .env and restart."
                )

            def run_reindex() -> dict[str, object]:
                return rebuild_index()

            return await run_with_trace(request, run_reindex)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
