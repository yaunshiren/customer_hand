from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.schemas import TrackerResponse
from app.core.exceptions import NotFoundError
from app.core.trace import trace_id_from_request, trace_scope
from app.core.tracker_store import InMemoryTrackerStore
from app.entry.guard import guard_tracker_full, guard_tracker_reset
from app.settings import settings

router = APIRouter()
LOCAL_TRACKER_DEBUG_ENVS = {"local", "development", "test"}


def _tracker_store(request: Request) -> InMemoryTrackerStore:
    return request.app.state.tracker_store


@router.get("/api/tracker/{sender_id}/full", response_model=TrackerResponse)
async def get_tracker_full(request: Request, sender_id: str) -> TrackerResponse:
    principal = guard_tracker_full(request, sender_id)
    with trace_scope(trace_id_from_request(request)):
        tracker = _tracker_store(request).retrieve(sender_id)
        if tracker is None:
            raise NotFoundError("tracker not found")

        roles = {role.strip().lower() for role in principal.roles if role.strip()}
        # Tracker has no trusted tenant_id yet. Full debug payloads therefore
        # remain local-only until S0-03 introduces tenant-aware ownership.
        allow_full_debug = (
            "admin" in roles
            and settings.app_env.strip().lower() in LOCAL_TRACKER_DEBUG_ENVS
        )
        if allow_full_debug:
            tracker_payload = tracker.to_dict()
        else:
            tracker_payload = {
                "flow_status": tracker.flow_status,
                "updated_at": tracker.updated_at,
            }

        return TrackerResponse(
            sender_id=sender_id,
            exists=True,
            tracker=tracker_payload,
        )


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
