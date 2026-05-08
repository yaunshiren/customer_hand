from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.agent.agent import Agent
from app.core.flow_loader import FlowLoader
from app.core.tracker_store import InMemoryTrackerStore
import uvicorn
from dotenv import load_dotenv

load_dotenv()

SERVICE_NAME = "customer_hand"
VERSION = "0.1.0"

app = FastAPI(title=SERVICE_NAME, version=VERSION)


class MessageRequest(BaseModel):
    sender_id: str = Field(default="user", min_length=1)
    message: str = Field(min_length=1)


class MessageResponse(BaseModel):
    recipient_id: str
    text: str | None = None
    timestamp: str
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": VERSION,
    }


store = InMemoryTrackerStore()
flows = FlowLoader().load_directory(Path("data/flows"))
agent = Agent(tracker_store=store, flows=flows)


@app.post("/api/messages", response_model=list[MessageResponse])
def send_message(req: MessageRequest) -> list[MessageResponse]:
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
        return {"error": "session not found"}
    return tracker


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
