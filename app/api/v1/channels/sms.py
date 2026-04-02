"""SMS channel endpoints — inbound webhook and outbound send."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_engine import ai_engine
from app.core.events import Event, event_bus
from app.core.handoff_engine import handoff_engine
from app.core.state_machine import ConversationState, Trigger
from app.db.models.conversation import Conversation
from app.dependencies import get_current_user_id, get_db, get_tenant_id
from app.providers.base import SMSMessage
from app.providers.registry import provider_registry
from app.services.message_service import message_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels/sms", tags=["sms"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class InboundSMSRequest(BaseModel):
    from_number: str
    content: str
    tenant_id: UUID


class SendSMSRequest(BaseModel):
    conversation_id: UUID
    content: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _find_or_create_sms_conversation(
    db: AsyncSession,
    tenant_id: UUID,
    from_number: str,
) -> tuple[Conversation, bool]:
    """Return an existing open SMS conversation for this number, or create a new one."""

    stmt = (
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.channel == "sms",
            Conversation.customer_identifier == from_number,
            Conversation.state.notin_(["ended", "failed"]),
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if conversation is not None:
        return conversation, False

    conversation = Conversation(
        tenant_id=tenant_id,
        channel="sms",
        direction="inbound",
        customer_identifier=from_number,
        state=ConversationState.AI_HANDLING.value,
        current_handler_type="ai",
        started_at=datetime.now(timezone.utc),
        answered_at=datetime.now(timezone.utc),
    )
    db.add(conversation)
    await db.flush()
    return conversation, True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/webhook", status_code=200)
async def sms_inbound_webhook(
    body: InboundSMSRequest,
    db: AsyncSession = Depends(get_db),
):
    """Receive an inbound SMS message from the provider webhook."""

    # 1. Find or create conversation
    conversation, created = await _find_or_create_sms_conversation(
        db,
        tenant_id=body.tenant_id,
        from_number=body.from_number,
    )

    # 2. Create the inbound message record
    message = await message_service.create_message(
        db=db,
        tenant_id=body.tenant_id,
        conversation_id=conversation.id,
        sender_type="customer",
        content=body.content,
        content_type="text",
    )

    # 3. If conversation is in AI handling state, process through AI engine
    if conversation.state == ConversationState.AI_HANDLING.value:
        recent_messages = await message_service.list_messages(
            db=db,
            tenant_id=body.tenant_id,
            conversation_id=conversation.id,
            limit=20,
        )
        history: list[dict] = []
        for msg in recent_messages:
            if msg.id == message.id:
                continue
            role = "assistant" if msg.sender_type == "ai" else "user"
            history.append({"role": role, "content": msg.content or ""})

        ai_response = await ai_engine.process_message(
            customer_message=body.content,
            conversation_history=history,
        )

        # Persist the AI response
        await message_service.create_message(
            db=db,
            tenant_id=body.tenant_id,
            conversation_id=conversation.id,
            sender_type="ai",
            content=ai_response.text,
            content_type="text",
            metadata={"confidence": ai_response.confidence},
        )

        # Escalate if needed
        if ai_response.should_escalate:
            try:
                await handoff_engine.process_trigger(
                    db=db,
                    conversation_id=conversation.id,
                    trigger=Trigger.AI_TRANSFER,
                    metadata={"reason": ai_response.escalation_reason},
                )
            except Exception:
                logger.exception(
                    "Failed to escalate SMS conversation %s after AI confidence drop",
                    conversation.id,
                )

    # 4. Publish inbound event
    await event_bus.publish(
        Event(
            topic="channel.sms.inbound",
            tenant_id=body.tenant_id,
            payload={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "from_number": body.from_number,
                "new_conversation": created,
            },
        )
    )

    return {"status": "ok", "conversation_id": str(conversation.id), "message_id": str(message.id)}


@router.post("/send")
async def sms_send_message(
    body: SendSMSRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user_id: UUID = Depends(get_current_user_id),
):
    """Send an outbound SMS message on behalf of an agent."""

    # Verify conversation exists and belongs to this tenant
    stmt = select(Conversation).where(
        Conversation.id == body.conversation_id,
        Conversation.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Get the SMS provider and send
    provider = await provider_registry.get_sms(tenant_id, db)

    sms_msg = SMSMessage(
        to_number=conversation.customer_identifier,
        body=body.content,
    )
    send_result = await provider.send_sms(tenant_id, sms_msg)

    # Create the outbound message record
    message = await message_service.create_message(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        sender_type="agent",
        sender_id=user_id,
        content=body.content,
        content_type="text",
        metadata={
            "provider_message_id": send_result.provider_message_id,
            "status": send_result.status,
        },
    )

    # Publish outbound event
    await event_bus.publish(
        Event(
            topic="channel.sms.outbound",
            tenant_id=tenant_id,
            payload={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "provider_message_id": send_result.provider_message_id,
            },
        )
    )

    return {
        "status": "sent",
        "message_id": str(message.id),
        "provider_message_id": send_result.provider_message_id,
    }
