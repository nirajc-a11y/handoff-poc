"""Conversation CRUD and messaging API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.handoff_engine import ConversationNotFoundError, handoff_engine
from app.core.state_machine import StateMachineError, Trigger
from app.dependencies import get_current_user_id, get_db, get_tenant_id
from app.services.conversation_service import conversation_service
from app.services.message_service import message_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateMessageRequest(BaseModel):
    content: str
    content_type: str = "text"
    sender_type: str = "agent"


class DispositionRequest(BaseModel):
    disposition: str
    notes: str | None = None


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _conversation_to_dict(conv) -> dict:
    return {
        "id": str(conv.id),
        "tenant_id": str(conv.tenant_id),
        "channel": conv.channel,
        "direction": conv.direction,
        "state": conv.state,
        "sub_state": conv.sub_state,
        "customer_identifier": conv.customer_identifier,
        "customer_name": conv.customer_name,
        "current_handler_type": conv.current_handler_type,
        "current_handler_id": str(conv.current_handler_id) if conv.current_handler_id else None,
        "lead_id": str(conv.lead_id) if conv.lead_id else None,
        "campaign_lead_id": str(conv.campaign_lead_id) if conv.campaign_lead_id else None,
        "queue_priority": conv.queue_priority,
        "started_at": conv.started_at.isoformat() if conv.started_at else None,
        "answered_at": conv.answered_at.isoformat() if conv.answered_at else None,
        "ended_at": conv.ended_at.isoformat() if conv.ended_at else None,
        "duration_seconds": conv.duration_seconds,
        "disposition": conv.disposition,
        "disposition_notes": conv.disposition_notes,
        "ai_confidence_score": conv.ai_confidence_score,
        "ai_escalation_reason": conv.ai_escalation_reason,
        "recording_url": conv.recording_url,
        "context": conv.context,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
    }


def _conversation_detail_to_dict(conv) -> dict:
    """Full detail including related messages, handoff events, and channel sessions."""
    base = _conversation_to_dict(conv)
    base["messages"] = [_message_to_dict(m) for m in (conv.messages or [])]
    base["handoff_events"] = [_handoff_event_to_dict(e) for e in (conv.handoff_events or [])]
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


def _message_to_dict(msg) -> dict:
    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "sender_type": msg.sender_type,
        "sender_id": str(msg.sender_id) if msg.sender_id else None,
        "content_type": msg.content_type,
        "content": msg.content,
        "metadata": msg.metadata_,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def _handoff_event_to_dict(evt) -> dict:
    return {
        "id": str(evt.id),
        "conversation_id": str(evt.conversation_id),
        "event_type": evt.event_type,
        "from_handler_type": evt.from_handler_type,
        "from_handler_id": str(evt.from_handler_id) if evt.from_handler_id else None,
        "to_handler_type": evt.to_handler_type,
        "to_handler_id": str(evt.to_handler_id) if evt.to_handler_id else None,
        "from_state": evt.from_state,
        "to_state": evt.to_state,
        "reason": evt.reason,
        "metadata": evt.metadata_,
        "created_at": evt.created_at.isoformat() if evt.created_at else None,
    }


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
    return [_conversation_to_dict(c) for c in conversations]


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
    return [_conversation_to_dict(c) for c in conversations]


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

    return _conversation_detail_to_dict(conversation)


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
    return [_message_to_dict(m) for m in messages]


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
    return _message_to_dict(message)


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
    return _message_to_dict(message)


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

    return [_handoff_event_to_dict(e) for e in (conversation.handoff_events or [])]


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

    return _conversation_to_dict(conversation)
