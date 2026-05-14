from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.agent.agent import Agent
from app.api.errors import bad_request, not_found, register_exception_handlers
from app.api.schemas import MessageRequest, MessageResponse
from app.core.flow_loader import FlowLoader
from app.core.tracker_store import InMemoryTrackerStore
from app.settings import settings

SERVICE_NAME = settings.app_name
VERSION = settings.app_version
BASE_DIR = Path(__file__).resolve().parent
INSPECT_TEMPLATE = BASE_DIR / "app" / "api" / "templates" / "inspect.html"


def create_app() -> FastAPI:
    store = InMemoryTrackerStore()
    flows = FlowLoader().load_directory(settings.flow_dir)
    agent = Agent(tracker_store=store, flows=flows)

    app = FastAPI(title=SERVICE_NAME, version=VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "version": VERSION,
        }

    @app.get("/inspect", response_class=FileResponse)
    def inspect_page() -> FileResponse:
        if not INSPECT_TEMPLATE.exists():
            raise not_found("inspect template not found")

        return FileResponse(INSPECT_TEMPLATE)

    @app.post("/api/messages", response_model=list[MessageResponse])
    def send_message(req: MessageRequest) -> list[MessageResponse]:
        if not req.message.strip():
            raise bad_request("message must not be empty")

        raw_responses = agent.handle_message(
            message=req.message,
            sender_id=req.sender_id,
        )
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

        return responses

    @app.get("/api/tracker/{sender_id}/full")
    def get_tracker_full(sender_id: str):
        tracker = store.retrieve(sender_id)
        if tracker is None:
            raise not_found("tracker not found")

        return {
            "sender_id": sender_id,
            "exists": True,
            "tracker": tracker,
        }

    @app.post("/api/tracker/{sender_id}/reset")
    def reset_tracker(sender_id: str):
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

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
