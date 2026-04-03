"""Conversation CRUD and messaging API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.handoff_engine import ConversationNotFoundError, handoff_engine
from app.core.state_machine import StateMachineError, Trigger
from app.dependencies import get_current_user_id, get_db, get_tenant_id
from app.schemas import (
    ContentTypeEnum,
    ConversationDetailResponse,
    ConversationResponse,
    HandoffEventResponse,
    MessageResponse,
    SenderTypeEnum,
)
from app.services.conversation_service import conversation_service
from app.services.message_service import message_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateMessageRequest(BaseModel):
    content: str
    content_type: ContentTypeEnum = ContentTypeEnum.text
    sender_type: SenderTypeEnum = SenderTypeEnum.agent


class DispositionRequest(BaseModel):
    disposition: str
    notes: str | None = None


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _conversation_response(conv) -> dict:
    return ConversationResponse.model_validate(conv).model_dump()


def _conversation_detail_response(conv) -> dict:
    """Full detail including related messages, handoff events, and channel sessions."""
    base = ConversationDetailResponse.model_validate(conv).model_dump()
    base["channel_sessions"] = [
        {
            "id": str(s.id),
            "channel": s.channel,
            "provider": s.provider,
            "provider_session_id": s.provider_session_id,
            "direction": s.direction,
            "from_address": s.from_address,
            "to_address": s.to_address,
            "started_at": s.started_at.isoformat() if s.started_at else None,
        }
        for s in (conv.channel_sessions or [])
    ]
    return base


def _message_response(msg) -> dict:
    return MessageResponse.model_validate(msg).model_dump()


def _handoff_event_response(evt) -> dict:
    return HandoffEventResponse.model_validate(evt).model_dump()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_conversations(
    state: str | None = Query(None, description="Filter by conversation state"),
    channel: str | None = Query(None, description="Filter by channel (voice, whatsapp, etc.)"),
    handler_id: UUID | None = Query(None, description="Filter by current handler agent id"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> list[dict]:
    """List conversations with optional filters."""
    conversations = await conversation_service.list_conversations(
        db=db,
        tenant_id=tenant_id,
        state=state,
        channel=channel,
        handler_id=handler_id,
        limit=limit,
        offset=offset,
    )
    return [_conversation_response(c) for c in conversations]


@router.get("/active")
async def list_active_conversations(
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> list[dict]:
    """List all active (non-ended, non-failed) conversations."""
    conversations = await conversation_service.get_active_conversations(
        db=db,
        tenant_id=tenant_id,
    )
    return [_conversation_response(c) for c in conversations]


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Get full conversation detail including messages, handoff events, and channel sessions."""
    conversation = await conversation_service.get_conversation(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return _conversation_detail_response(conversation)


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> list[dict]:
    """List messages for a conversation in chronological order."""
    messages = await message_service.list_messages(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )
    return [_message_response(m) for m in messages]


@router.post("/{conversation_id}/messages")
async def create_message(
    conversation_id: UUID,
    body: CreateMessageRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user_id: UUID = Depends(get_current_user_id),
) -> dict:
    """Append a message to a conversation."""
    message = await message_service.create_message(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        sender_type=body.sender_type,
        content=body.content,
        content_type=body.content_type,
        sender_id=user_id,
    )
    return _message_response(message)


@router.post("/{conversation_id}/audio-message")
async def upload_audio_message(
    conversation_id: UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user_id: UUID = Depends(get_current_user_id),
) -> dict:
    """Upload a browser-recorded audio file and save as a message."""
    import os

    conversation = await conversation_service.get_conversation(db=db, tenant_id=tenant_id, conversation_id=conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    recordings_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "recordings")
    os.makedirs(recordings_dir, exist_ok=True)

    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "webm"
    filename = f"{conversation_id}_agent_{timestamp}.{ext}"
    filepath = os.path.join(recordings_dir, filename)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    recording_path = f"/recordings/{filename}"
    message = await message_service.create_message(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        sender_type="agent",
        content=recording_path,
        content_type="audio",
        sender_id=user_id,
    )
    return _message_response(message)


@router.get("/{conversation_id}/handoffs")
async def list_handoff_events(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> list[dict]:
    """List handoff events for a conversation."""
    conversation = await conversation_service.get_conversation(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return [_handoff_event_response(e) for e in (conversation.handoff_events or [])]


@router.post("/{conversation_id}/disposition")
async def submit_disposition(
    conversation_id: UUID,
    body: DispositionRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Set disposition on a conversation and transition to ENDED."""
    try:
        await conversation_service.set_disposition(
            db=db,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            disposition=body.disposition,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=Trigger.DISPOSITION_SUBMITTED,
            metadata={
                "disposition": body.disposition,
                "disposition_notes": body.notes,
            },
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _conversation_response(conversation)
