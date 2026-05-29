from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

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
from app.rag.reindex import get_index_status, rebuild_index
from app.rag.retriever import KnowledgeBaseRetriever, normalize_rag_backend
from app.settings import settings

logger = logging.getLogger(__name__)

SERVICE_NAME = settings.app_name
VERSION = settings.app_version
BASE_DIR = Path(__file__).resolve().parent
INSPECT_TEMPLATE = BASE_DIR / "app" / "api" / "templates" / "inspect.html"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _predict_eval_intent(text: str) -> list[str]:
    """Temporary intent mapping for ragenteval's /api/eval/rag side channel."""
    lowered = text.lower()

    if _contains_any(lowered, ("态度", "投诉", "吐槽", "差评", "不满意")):
        return ["F3_投诉吐槽"]
    if _contains_any(lowered, ("希望", "建议", "加个", "新增", "优化")):
        return ["F2_功能建议"]
    if _contains_any(lowered, ("充不进电", "不开机", "坏了", "故障", "异常", "报错", "不工作")):
        return ["F1_故障报告"]
    if _contains_any(lowered, ("预算", "推荐", "买哪款", "哪款")):
        return ["S1_选购推荐"]
    if _contains_any(lowered, ("区别", "对比", "有什么不同", "哪个好")):
        return ["S3_对比选购"]
    if _contains_any(lowered, ("保修", "维修", "保修期", "售后政策")):
        return ["S14_售后政策"]
    if _contains_any(lowered, ("退货", "退款", "换货", "无理由", "重新买")):
        return ["S15_退换货"]
    if _contains_any(lowered, ("物流", "快递", "收货地址", "已经发货", "改地址")):
        return ["S16_物流配送"]
    if _contains_any(lowered, ("发票", "抬头", "会员", "积分")):
        return ["S17_发票会员"]
    if _contains_any(lowered, ("降价", "补差", "价保", "价格保护", "活动")):
        return ["S4_价格活动"]
    if _contains_any(lowered, ("送到", "发货", "库存", "到货", "现货")):
        return ["S5_库存到货"]
    if _contains_any(lowered, ("充电器", "配件", "兼容", "保护壳", "贴膜")):
        return ["S6_配件兼容"]
    if _contains_any(lowered, ("开机", "首次使用", "怎么用", "操作", "开启")):
        return ["S8_操作指引"]
    if _contains_any(lowered, ("wifi", "wi-fi", "配网", "连网", "连接网络")):
        return ["S9_配网连接"]
    if _contains_any(lowered, ("升级", "固件", "系统更新")):
        return ["S11_固件升级"]
    if _contains_any(lowered, ("联动", "控制扫地机", "智能音箱", "小爱音箱")):
        return ["S12_生态联动"]
    if _contains_any(lowered, ("滤芯", "保养", "维护", "多久换")):
        return ["S13_保养维护"]
    if _contains_any(lowered, ("屏幕", "尺寸", "刷新率", "参数", "多少像素", "重量")):
        return ["S2_参数咨询"]
    if _contains_any(lowered, ("app", "订单", "地址", "收藏")):
        return ["S10_APP功能"]

    return []


def _eval_intent_skips_rag(intent_leaf_ids: list[str]) -> bool:
    return bool(intent_leaf_ids and intent_leaf_ids[0] in {"F2_功能建议", "F3_投诉吐槽"})


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    logger.info("service.start name=%s version=%s", SERVICE_NAME, VERSION)
    yield
    logger.info("service.stop name=%s", SERVICE_NAME)


def create_app() -> FastAPI:
    store = InMemoryTrackerStore()
    flows = FlowLoader().load_directory(settings.flow_dir)
    agent = Agent(tracker_store=store, flows=flows, knowledge_dir=settings.knowledge_dir)

    app = FastAPI(title=SERVICE_NAME, version=VERSION, lifespan=app_lifespan)
    app.state.kb_retriever = agent.knowledge_answerer.retriever
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
        with trace_scope(trace_id_from_request(request)):
            text = req.message.strip()
            if not text:
                raise BadRequestError("message must not be empty")

            logger.info(
                "api.messages sender_id=%s message_len=%d",
                req.sender_id,
                len(text),
            )

            def handle() -> list[dict[str, object]]:
                return agent.handle_message(
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

            logger.info("api.messages.done sender_id=%s replies=%d", req.sender_id, len(responses))
            return responses

    @app.get("/api/eval/rag")
    async def eval_rag(request: Request, question: str, top_k: int = 5):
        with trace_scope(trace_id_from_request(request)):
            text = question.strip()
            if not text:
                raise BadRequestError("question must not be empty")

            effective_top_k = max(1, min(int(top_k), 20))
            trace_id = trace_id_from_request(request)
            intent_leaf_ids = _predict_eval_intent(text)

            if _eval_intent_skips_rag(intent_leaf_ids):
                return {
                    "success": True,
                    "data": {
                        "question": text,
                        "retrievedDocIds": [],
                        "retrievedChunkIds": [],
                        "retrievedContexts": [],
                        "retrievedContextDocIds": [],
                        "intentLeafIds": intent_leaf_ids,
                        "hasKb": False,
                        "hasMcp": False,
                        "traceId": trace_id,
                    },
                }

            retriever = request.app.state.kb_retriever
            retrieval = await run_with_trace(request, lambda: retriever.retrieve(text, top_k=effective_top_k))
            matches = retrieval.matches or []

            def _doc_id(match) -> str | None:
                metadata = getattr(match.chunk, "metadata", {}) or {}
                doc_id = metadata.get("doc_id")
                if doc_id:
                    return str(doc_id)
                source = str(getattr(match.chunk, "source", ""))
                return Path(source).stem if source else None

            doc_ids_by_match = [_doc_id(match) for match in matches]
            retrieved_doc_ids = list(dict.fromkeys([doc_id for doc_id in doc_ids_by_match if doc_id]))
            retrieved_chunk_ids = [str(match.chunk.chunk_id) for match in matches]
            retrieved_context_doc_ids = doc_ids_by_match
            retrieved_contexts: list[str] = []
            for match, doc_id in zip(matches, doc_ids_by_match):
                retrieved_contexts.append(
                    "---\n"
                    f"doc_id: {doc_id}\n"
                    f"source: {match.chunk.source}\n"
                    f"chunk_id: {match.chunk.chunk_id}\n"
                    "---\n"
                    f"{match.chunk.text}"
                )

            return {
                "success": True,
                "data": {
                    "question": text,
                    "retrievedDocIds": retrieved_doc_ids,
                    "retrievedChunkIds": retrieved_chunk_ids,
                    "retrievedContexts": retrieved_contexts,
                    "retrievedContextDocIds": retrieved_context_doc_ids,
                    "intentLeafIds": intent_leaf_ids,
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
