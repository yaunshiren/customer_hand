from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.agent.agent import Agent
from app.api.errors import register_exception_handlers
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.messages import router as messages_router
from app.api.routes.system import router as system_router
from app.api.routes.tracker import router as tracker_router
from app.core.flow_loader import FlowLoader
from app.core.logging import configure_logging
from app.core.trace import new_trace_id
from app.core.tracker_store import InMemoryTrackerStore
from app.persistence.trace_recorder import AgentTraceRecorder
from app.settings import settings

logger = logging.getLogger(__name__)

SERVICE_NAME = settings.app_name
VERSION = settings.app_version


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    logger.info("service.start name=%s version=%s", SERVICE_NAME, VERSION)
    yield
    logger.info("service.stop name=%s", SERVICE_NAME)


async def trace_header_middleware(request: Request, call_next):
    incoming = request.headers.get("x-trace-id") or request.headers.get("x-request-id")
    trace_id = (incoming or "").strip() or new_trace_id()
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-Id"] = str(getattr(request.state, "trace_id", trace_id))
    return response


def register_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(trace_header_middleware)


def register_routers(app: FastAPI) -> None:
    app.include_router(system_router)
    app.include_router(messages_router)
    app.include_router(knowledge_router)
    app.include_router(tracker_router)


def create_app() -> FastAPI:
    tracker_store = InMemoryTrackerStore(memory_turn_limit=settings.memory_recent_turn_limit)
    flows = FlowLoader().load_directory(settings.flow_dir)
    agent = Agent(
        tracker_store=tracker_store,
        flows=flows,
        knowledge_dir=settings.knowledge_dir,
    )

    app = FastAPI(title=SERVICE_NAME, version=VERSION, lifespan=app_lifespan)
    app.state.agent = agent
    app.state.tracker_store = tracker_store
    app.state.kb_retriever = agent.knowledge_answerer.retriever
    app.state.trace_recorder = AgentTraceRecorder()

    register_middleware(app)
    register_exception_handlers(app)
    register_routers(app)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
