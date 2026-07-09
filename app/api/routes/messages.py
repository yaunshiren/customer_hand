from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.schemas import MessageRequest, MessageResponse
from app.services.message_service import process_message

router = APIRouter()


@router.post("/api/messages", response_model=list[MessageResponse])
async def send_message(req: MessageRequest, request: Request) -> list[MessageResponse]:
    return await process_message(req, request)
