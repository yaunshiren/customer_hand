from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.exceptions import BadRequestError
from app.core.trace import run_with_trace, trace_id_from_request, trace_scope
from app.entry.guard import guard_eval_rag, guard_knowledge_reindex
from app.rag.citation import CitationBuilder
from app.rag.reindex import get_index_status, rebuild_index
from app.rag.retriever import normalize_rag_backend
from app.settings import settings

router = APIRouter()


@router.get("/api/eval/rag")
async def eval_rag(request: Request, question: str, top_k: int = 5):
    guard_eval_rag(request)
    with trace_scope(trace_id_from_request(request)):
        text = question.strip()
        if not text:
            raise BadRequestError("question must not be empty")

        effective_top_k = max(1, min(int(top_k), 20))
        trace_id = trace_id_from_request(request)
        retriever = request.app.state.kb_retriever
        retrieval = await run_with_trace(
            request,
            lambda: retriever.retrieve(text, top_k=effective_top_k),
        )
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


@router.get("/api/knowledge/status")
async def knowledge_status(request: Request):
    with trace_scope(trace_id_from_request(request)):
        status = get_index_status()
        status["rag_backend"] = settings.rag_backend
        return status


@router.post("/api/knowledge/reindex")
async def knowledge_reindex(request: Request):
    guard_knowledge_reindex(request)
    with trace_scope(trace_id_from_request(request)):
        if normalize_rag_backend(settings.rag_backend) != "chroma":
            raise BadRequestError(
                "RAG_BACKEND must be chroma to rebuild vector index. "
                "Set RAG_BACKEND=chroma in .env and restart."
            )

        def run_reindex() -> dict[str, object]:
            return rebuild_index()

        return await run_with_trace(request, run_reindex)
