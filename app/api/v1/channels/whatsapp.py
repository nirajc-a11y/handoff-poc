"""WhatsApp channel endpoints — inbound webhook, outbound send, and template messages."""

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
from app.providers.base import WhatsAppMessage
from app.providers.registry import provider_registry
from app.schemas import PhoneNumber
from app.services.message_service import message_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels/whatsapp", tags=["whatsapp"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class InboundWebhookRequest(BaseModel):
    from_number: PhoneNumber
    content: str
    content_type: str = "text"
    tenant_id: UUID


class SendMessageRequest(BaseModel):
    conversation_id: UUID
    content: str
    content_type: str = "text"


class SendTemplateRequest(BaseModel):
    to_number: str
    template_name: str
    template_params: dict | None = None
    customer_name: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _find_or_create_conversation(
    db: AsyncSession,
    tenant_id: UUID,
    customer_identifier: str,
    direction: str,
    customer_name: str | None = None,
) -> tuple[Conversation, bool]:
    """Return an existing open conversation or create a new one.

    Returns ``(conversation, created)`` where *created* is True when a new
    row was inserted.
    """
    stmt = (
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.channel == "whatsapp",
            Conversation.customer_identifier == customer_identifier,
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
        channel="whatsapp",
        direction=direction,
        customer_identifier=customer_identifier,
        customer_name=customer_name,
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
async def whatsapp_inbound_webhook(
    body: InboundWebhookRequest,
    db: AsyncSession = Depends(get_db),
):
    """Receive an inbound WhatsApp message from the provider webhook."""

    # 1. Find or create conversation
    conversation, created = await _find_or_create_conversation(
        db,
        tenant_id=body.tenant_id,
        customer_identifier=body.from_number,
        direction="inbound",
    )

    # 2. Create the inbound message record
    message = await message_service.create_message(
        db=db,
        tenant_id=body.tenant_id,
        conversation_id=conversation.id,
        sender_type="customer",
        content=body.content,
        content_type=body.content_type,
    )

    # 3. If the conversation is in AI handling state, process through AI engine
    if conversation.state == ConversationState.AI_HANDLING.value:
        # Build a lightweight conversation history from recent messages
        from app.services.message_service import message_service as _ms

        recent_messages = await _ms.list_messages(
            db=db,
            tenant_id=body.tenant_id,
            conversation_id=conversation.id,
            limit=20,
        )
        history: list[dict] = []
        for msg in recent_messages:
            if msg.id == message.id:
                continue  # skip the message we just created; it goes as the user prompt
            role = "assistant" if msg.sender_type == "ai" else "user"
            history.append({"role": role, "content": msg.content or ""})

        ai_response = await ai_engine.process_message(
            customer_message=body.content,
            conversation_history=history,
        )

        # Persist the AI response as a message
        await message_service.create_message(
            db=db,
            tenant_id=body.tenant_id,
            conversation_id=conversation.id,
            sender_type="ai",
            content=ai_response.text,
            content_type="text",
            metadata={"confidence": ai_response.confidence},
        )

        # If the AI thinks we should escalate, trigger a handoff
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
                    "Failed to escalate conversation %s after AI confidence drop",
                    conversation.id,
                )

    # 4. Publish inbound event
    await event_bus.publish(
        Event(
            topic="channel.whatsapp.inbound",
            tenant_id=body.tenant_id,
            payload={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "from_number": body.from_number,
                "content_type": body.content_type,
                "new_conversation": created,
            },
        )
    )

    return {"status": "ok", "conversation_id": str(conversation.id), "message_id": str(message.id)}


@router.post("/send")
async def whatsapp_send_message(
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user_id: UUID = Depends(get_current_user_id),
):
    """Send an outbound WhatsApp message on behalf of an agent."""

    # Verify conversation exists and belongs to this tenant
    stmt = select(Conversation).where(
        Conversation.id == body.conversation_id,
        Conversation.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Get the WhatsApp provider for this tenant
    provider = await provider_registry.get_whatsapp(tenant_id, db)

    wa_message = WhatsAppMessage(
        to_number=conversation.customer_identifier,
        content=body.content,
        content_type=body.content_type,
    )
    send_result = await provider.send_message(tenant_id, wa_message)

    # Create the outbound message record
    message = await message_service.create_message(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        sender_type="agent",
        sender_id=user_id,
        content=body.content,
        content_type=body.content_type,
        metadata={
            "provider_message_id": send_result.provider_message_id,
            "status": send_result.status,
        },
    )

    # Publish outbound event
    await event_bus.publish(
        Event(
            topic="channel.whatsapp.outbound",
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


@router.post("/template")
async def whatsapp_send_template(
    body: SendTemplateRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    """Send a WhatsApp template message, initiating a new outbound conversation."""

    # Create a new outbound conversation
    conversation = Conversation(
        tenant_id=tenant_id,
        channel="whatsapp",
        direction="outbound",
        customer_identifier=body.to_number,
        customer_name=body.customer_name,
        state=ConversationState.INITIATED.value,
        current_handler_type="system",
        started_at=datetime.now(timezone.utc),
    )
    db.add(conversation)
    await db.flush()

    # Send template via provider
    provider = await provider_registry.get_whatsapp(tenant_id, db)

    wa_message = WhatsAppMessage(
        to_number=body.to_number,
        content="",
        content_type="template",
        template_name=body.template_name,
        template_params=body.template_params,
    )
    send_result = await provider.send_template(tenant_id, wa_message)

    # Record the template message
    message = await message_service.create_message(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        sender_type="system",
        content=f"[Template: {body.template_name}]",
        content_type="template",
        metadata={
            "template_name": body.template_name,
            "template_params": body.template_params,
            "provider_message_id": send_result.provider_message_id,
            "status": send_result.status,
        },
    )

    await db.commit()

    # Publish event
    await event_bus.publish(
        Event(
            topic="channel.whatsapp.template_sent",
            tenant_id=tenant_id,
            payload={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "template_name": body.template_name,
                "to_number": body.to_number,
                "provider_message_id": send_result.provider_message_id,
            },
        )
    )

    return {
        "status": "sent",
        "conversation_id": str(conversation.id),
        "message_id": str(message.id),
        "provider_message_id": send_result.provider_message_id,
    }
