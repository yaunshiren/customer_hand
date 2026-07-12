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
    authorization = guard_tracker_full(request, sender_id)
    with trace_scope(trace_id_from_request(request)):
        tracker = _tracker_store(request).retrieve(
            authorization,
            owner_user_id=sender_id,
        )
        if tracker is None:
            raise NotFoundError("tracker not found")

        # Full debug remains narrower than tenant-admin access: only a local
        # server-configured admin reading its own Tracker receives internals.
        allow_full_debug = (
            authorization.is_tenant_admin
            and authorization.owner_user_id == tracker.owner_user_id
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
    authorization = guard_tracker_reset(request, sender_id)
    with trace_scope(trace_id_from_request(request)):
        deleted = _tracker_store(request).delete(
            authorization,
            owner_user_id=sender_id,
        )
        if not deleted:
            # A resource outside the caller's tenant is indistinguishable from
            # a resource that does not exist in the caller's tenant.
            raise NotFoundError("tracker not found")
        return {
            "sender_id": sender_id,
            "reset": True,
            "message": "Tracker reset successfully",
        }
