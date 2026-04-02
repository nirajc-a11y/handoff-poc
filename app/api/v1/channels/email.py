"""Email channel endpoints — inbound webhook, outbound send, and thread retrieval."""

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
from app.db.models.message import Message
from app.dependencies import get_current_user_id, get_db, get_tenant_id
from app.providers.base import EmailMessage
from app.providers.registry import provider_registry
from app.services.message_service import message_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels/email", tags=["email"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class InboundEmailRequest(BaseModel):
    from_address: str
    to_address: str
    subject: str
    body_html: str
    body_text: str | None = None
    tenant_id: UUID
    in_reply_to: str | None = None
    message_id: str | None = None


class SendEmailRequest(BaseModel):
    conversation_id: UUID
    subject: str | None = None
    body_html: str
    body_text: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _find_conversation_by_thread(
    db: AsyncSession,
    tenant_id: UUID,
    in_reply_to: str | None,
) -> Conversation | None:
    """Try to locate an existing conversation by email threading headers.

    We match if any message in an open conversation has an ``email_message_id``
    equal to the incoming ``in_reply_to`` value.
    """
    if not in_reply_to:
        return None

    stmt = (
        select(Conversation)
        .join(Message, Message.conversation_id == Conversation.id)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.channel == "email",
            Conversation.state.notin_(["ended", "failed"]),
            Message.email_message_id == in_reply_to,
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _find_or_create_email_conversation(
    db: AsyncSession,
    tenant_id: UUID,
    from_address: str,
    subject: str,
    in_reply_to: str | None,
) -> tuple[Conversation, bool]:
    """Return an existing conversation matched by thread, or create a new one."""

    # Attempt thread-based match first
    conversation = await _find_conversation_by_thread(db, tenant_id, in_reply_to)
    if conversation is not None:
        return conversation, False

    # Fallback: look for any open email conversation with this sender
    stmt = (
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.channel == "email",
            Conversation.customer_identifier == from_address,
            Conversation.state.notin_(["ended", "failed"]),
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    if conversation is not None:
        return conversation, False

    # Create a brand-new conversation
    conversation = Conversation(
        tenant_id=tenant_id,
        channel="email",
        direction="inbound",
        customer_identifier=from_address,
        state=ConversationState.AI_HANDLING.value,
        current_handler_type="ai",
        started_at=datetime.now(timezone.utc),
        answered_at=datetime.now(timezone.utc),
        context={"subject": subject},
    )
    db.add(conversation)
    await db.flush()
    return conversation, True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/webhook", status_code=200)
async def email_inbound_webhook(
    body: InboundEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Receive an inbound email from the provider webhook."""

    # 1. Find or create conversation
    conversation, created = await _find_or_create_email_conversation(
        db,
        tenant_id=body.tenant_id,
        from_address=body.from_address,
        subject=body.subject,
        in_reply_to=body.in_reply_to,
    )

    # 2. Create the inbound message with email threading fields
    message = await message_service.create_message(
        db=db,
        tenant_id=body.tenant_id,
        conversation_id=conversation.id,
        sender_type="customer",
        content=body.body_html,
        content_type="email",
        metadata={
            "from_address": body.from_address,
            "to_address": body.to_address,
            "subject": body.subject,
            "body_text": body.body_text,
        },
    )

    # Set email-specific threading columns (not covered by create_message)
    message.email_message_id = body.message_id
    message.email_in_reply_to = body.in_reply_to
    message.email_subject = body.subject
    await db.commit()

    # 3. If conversation is in AI handling state, process through AI engine
    if conversation.state == ConversationState.AI_HANDLING.value:
        # Use the plain-text body for AI processing (falls back to HTML)
        ai_input = body.body_text or body.body_html

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
            customer_message=ai_input,
            conversation_history=history,
        )

        ai_msg = await message_service.create_message(
            db=db,
            tenant_id=body.tenant_id,
            conversation_id=conversation.id,
            sender_type="ai",
            content=ai_response.text,
            content_type="text",
            metadata={"confidence": ai_response.confidence},
        )

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
            topic="channel.email.inbound",
            tenant_id=body.tenant_id,
            payload={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "from_address": body.from_address,
                "subject": body.subject,
                "new_conversation": created,
            },
        )
    )

    return {"status": "ok", "conversation_id": str(conversation.id), "message_id": str(message.id)}


@router.post("/send")
async def email_send(
    body: SendEmailRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user_id: UUID = Depends(get_current_user_id),
):
    """Send an outbound email reply on behalf of an agent."""

    # Verify conversation exists
    stmt = select(Conversation).where(
        Conversation.id == body.conversation_id,
        Conversation.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Determine the subject and threading info from conversation context
    subject = body.subject or (conversation.context or {}).get("subject", "Re: Your enquiry")

    # Get the latest message's email_message_id for threading
    recent = await message_service.list_messages(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        limit=1,
    )
    in_reply_to = recent[-1].email_message_id if recent and recent[-1].email_message_id else None

    # Get the email provider and send
    provider = await provider_registry.get_email(tenant_id, db)

    email_msg = EmailMessage(
        to=[conversation.customer_identifier],
        subject=subject,
        body_html=body.body_html,
        body_text=body.body_text,
        in_reply_to=in_reply_to,
    )
    send_result = await provider.send_email(tenant_id, email_msg)

    # Create the outbound message record
    message = await message_service.create_message(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        sender_type="agent",
        sender_id=user_id,
        content=body.body_html,
        content_type="email",
        metadata={
            "provider_message_id": send_result.provider_message_id,
            "status": send_result.status,
            "subject": subject,
            "body_text": body.body_text,
        },
    )

    # Set email threading columns
    message.email_message_id = send_result.message_id_header
    message.email_in_reply_to = in_reply_to
    message.email_subject = subject
    await db.commit()

    # Publish outbound event
    await event_bus.publish(
        Event(
            topic="channel.email.outbound",
            tenant_id=tenant_id,
            payload={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "provider_message_id": send_result.provider_message_id,
                "subject": subject,
            },
        )
    )

    return {
        "status": "sent",
        "message_id": str(message.id),
        "provider_message_id": send_result.provider_message_id,
        "email_message_id": send_result.message_id_header,
    }


@router.get("/{conversation_id}/thread")
async def email_get_thread(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    """Retrieve the full email thread for a conversation, ordered chronologically."""

    # Verify conversation exists
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id,
        Conversation.channel == "email",
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Email conversation not found")

    messages = await message_service.list_messages(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )

    return {
        "conversation_id": str(conversation_id),
        "subject": (conversation.context or {}).get("subject"),
        "messages": [
            {
                "id": str(msg.id),
                "sender_type": msg.sender_type,
                "sender_id": str(msg.sender_id) if msg.sender_id else None,
                "content": msg.content,
                "content_type": msg.content_type,
                "email_message_id": msg.email_message_id,
                "email_in_reply_to": msg.email_in_reply_to,
                "email_subject": msg.email_subject,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
        ],
    }
