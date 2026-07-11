from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.core.exceptions import NotFoundError
from app.core.trace import trace_id_from_request, trace_scope
from app.entry.guard import guard_inspect_page
from app.settings import settings

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INSPECT_TEMPLATE = PROJECT_ROOT / "app" / "api" / "templates" / "inspect.html"
DEVELOPMENT_ENVS = {"dev", "development", "local", "test"}


@router.get("/health")
async def health(request: Request):
    with trace_scope(trace_id_from_request(request)):
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": settings.app_version,
        }


@router.get("/inspect", response_class=FileResponse)
async def inspect_page(request: Request) -> FileResponse:
    if settings.app_env.strip().lower() not in DEVELOPMENT_ENVS:
        guard_inspect_page(request)
    with trace_scope(trace_id_from_request(request)):
        if not INSPECT_TEMPLATE.exists():
            raise NotFoundError("inspect template not found")
        return FileResponse(INSPECT_TEMPLATE)
