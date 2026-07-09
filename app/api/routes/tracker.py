from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.exceptions import NotFoundError
from app.core.trace import trace_id_from_request, trace_scope
from app.entry.guard import guard_tracker_reset
from app.core.tracker_store import InMemoryTrackerStore

router = APIRouter()


def _tracker_store(request: Request) -> InMemoryTrackerStore:
    return request.app.state.tracker_store


@router.get("/api/tracker/{sender_id}/full")
async def get_tracker_full(request: Request, sender_id: str):
    with trace_scope(trace_id_from_request(request)):
        tracker = _tracker_store(request).retrieve(sender_id)
        if tracker is None:
            raise NotFoundError("tracker not found")

        return {
            "sender_id": sender_id,
            "exists": True,
            "tracker": tracker,
        }


@router.post("/api/tracker/{sender_id}/reset")
async def reset_tracker(request: Request, sender_id: str):
    guard_tracker_reset(request, sender_id)
    with trace_scope(trace_id_from_request(request)):
        deleted = _tracker_store(request).delete(sender_id)
        return {
            "sender_id": sender_id,
            "reset": deleted,
            "message": (
                "Tracker reset successfully"
                if deleted
                else "Tracker did not exist"
            ),
        }
