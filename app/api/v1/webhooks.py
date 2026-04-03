"""Generic provider webhooks — telephony callbacks, delivery receipts, and bounce notifications."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, event_bus
from app.core.handoff_engine import handoff_engine
from app.core.state_machine import StateMachineError, Trigger
from app.db.models.channel_session import ChannelSession
from app.dependencies import get_db
from app.providers.base import CallState
from app.schemas import TelephonyProviderEnum

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Call-state to Trigger mapping
# ---------------------------------------------------------------------------

_CALL_STATE_TRIGGER_MAP: dict[CallState, Trigger] = {
    CallState.RINGING: Trigger.RING,
    CallState.ANSWERED: Trigger.ANSWER,
    CallState.ENDED: Trigger.CUSTOMER_DISCONNECT,
    CallState.FAILED: Trigger.ERROR,
    CallState.BUSY: Trigger.BUSY,
    CallState.NO_ANSWER: Trigger.NO_ANSWER,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_call_state(provider: str, payload: dict) -> tuple[str, CallState]:
    """Extract the provider session ID and call state from a provider-specific payload.

    Each provider sends a different payload shape.  We normalise the common
    fields here.  For unrecognised providers we fall back to a generic
    ``call_id`` / ``status`` shape.
    """
    if provider == "twilio":
        session_id = payload.get("CallSid", "")
        status_raw = payload.get("CallStatus", "").lower()
    elif provider == "exotel":
        session_id = payload.get("Sid") or payload.get("CallSid", "")
        status_raw = payload.get("Status", "").lower()
    elif provider == "plivo":
        session_id = payload.get("CallUUID", "")
        status_raw = payload.get("CallStatus", "").lower()
    else:
        # Generic fallback
        session_id = payload.get("call_id") or payload.get("session_id", "")
        status_raw = payload.get("status") or payload.get("state", "")
        status_raw = status_raw.lower() if isinstance(status_raw, str) else ""

    # Map the raw status string to a CallState enum
    _STATUS_ALIASES: dict[str, CallState] = {
        "initiated": CallState.INITIATED,
        "ringing": CallState.RINGING,
        "in-progress": CallState.ANSWERED,
        "answered": CallState.ANSWERED,
        "connected": CallState.CONNECTED,
        "completed": CallState.ENDED,
        "ended": CallState.ENDED,
        "failed": CallState.FAILED,
        "busy": CallState.BUSY,
        "no-answer": CallState.NO_ANSWER,
        "no_answer": CallState.NO_ANSWER,
        "canceled": CallState.FAILED,
        "cancelled": CallState.FAILED,
    }

    call_state = _STATUS_ALIASES.get(status_raw)
    if call_state is None:
        raise ValueError(f"Unknown call status '{status_raw}' from provider '{provider}'")

    return session_id, call_state


async def _find_session(
    db: AsyncSession,
    provider: str,
    provider_session_id: str,
) -> ChannelSession | None:
    """Find a ChannelSession by provider name and provider-side session ID."""
    stmt = (
        select(ChannelSession)
        .where(
            ChannelSession.provider == provider,
            ChannelSession.provider_session_id == provider_session_id,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Telephony webhook
# ---------------------------------------------------------------------------

@router.post("/telephony/{provider}")
async def telephony_webhook(
    provider: TelephonyProviderEnum,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """Generic telephony callback — receives call state updates from any
    telephony provider, maps them to the internal state machine, and triggers
    transitions through the handoff engine.
    """
    try:
        provider_session_id, call_state = _extract_call_state(provider, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not provider_session_id:
        raise HTTPException(status_code=400, detail="Missing session/call ID in payload")

    # Look up the channel session
    session = await _find_session(db, provider, provider_session_id)
    if session is None:
        logger.warning(
            "No ChannelSession found for provider=%s, session_id=%s — ignoring",
            provider,
            provider_session_id,
        )
        return {"status": "ignored", "reason": "session_not_found"}

    # Update session status
    session.status = call_state.value
    session.provider_metadata = {**(session.provider_metadata or {}), "last_payload": payload}
    await db.flush()

    # Map call state to a Trigger
    trigger = _CALL_STATE_TRIGGER_MAP.get(call_state)
    if trigger is None:
        logger.info(
            "Call state %s has no mapped trigger — skipping handoff engine (session=%s)",
            call_state.value,
            provider_session_id,
        )
        await db.commit()
        return {"status": "ok", "call_state": call_state.value, "trigger": None}

    # Process the trigger through the handoff engine
    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=session.conversation_id,
            trigger=trigger,
            metadata={
                "provider": provider,
                "provider_session_id": provider_session_id,
                "call_state": call_state.value,
                "raw_payload": payload,
            },
        )
    except StateMachineError as exc:
        logger.warning(
            "Invalid state transition for conversation %s: %s",
            session.conversation_id,
            exc,
        )
        return {"status": "ignored", "reason": str(exc)}

    return {
        "status": "processed",
        "conversation_id": str(session.conversation_id),
        "call_state": call_state.value,
        "trigger": trigger.value,
        "new_state": conversation.state,
    }


# ---------------------------------------------------------------------------
# WhatsApp delivery receipts
# ---------------------------------------------------------------------------

@router.post("/whatsapp/{provider}")
async def whatsapp_delivery_webhook(
    provider: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """Handle WhatsApp delivery receipts and status updates from providers."""

    # Extract common fields (provider-specific parsing)
    message_id = (
        payload.get("MessageSid")  # Twilio
        or payload.get("message_id")  # Generic
        or payload.get("id", "")
    )
    status = (
        payload.get("MessageStatus")  # Twilio
        or payload.get("status")  # Generic
        or "unknown"
    )

    logger.info(
        "WhatsApp delivery receipt from %s: message_id=%s, status=%s",
        provider,
        message_id,
        status,
    )

    # Publish a delivery event for downstream consumers
    # We extract tenant_id from the payload if available; otherwise this is
    # a best-effort fire-and-forget.
    tenant_id_raw = payload.get("tenant_id")
    if tenant_id_raw:
        try:
            tid = UUID(str(tenant_id_raw))
        except (ValueError, AttributeError):
            tid = None
    else:
        tid = None

    if tid:
        await event_bus.publish(
            Event(
                topic="channel.whatsapp.delivery",
                tenant_id=tid,
                payload={
                    "provider": provider,
                    "provider_message_id": message_id,
                    "status": status,
                    "raw_payload": payload,
                },
            )
        )

    return {"status": "ok", "provider_message_id": message_id, "delivery_status": status}


# ---------------------------------------------------------------------------
# Email bounce / delivery notifications
# ---------------------------------------------------------------------------

@router.post("/email/{provider}")
async def email_delivery_webhook(
    provider: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """Handle email bounce, delivery, and complaint notifications from providers."""

    # Normalise common fields
    notification_type = (
        payload.get("notificationType")  # AWS SES
        or payload.get("event")  # SendGrid
        or payload.get("type")  # Generic
        or "unknown"
    )
    message_id = (
        payload.get("mail", {}).get("messageId")  # AWS SES
        or payload.get("sg_message_id")  # SendGrid
        or payload.get("message_id", "")
    )

    logger.info(
        "Email notification from %s: type=%s, message_id=%s",
        provider,
        notification_type,
        message_id,
    )

    tenant_id_raw = payload.get("tenant_id")
    if tenant_id_raw:
        try:
            tid = UUID(str(tenant_id_raw))
        except (ValueError, AttributeError):
            tid = None
    else:
        tid = None

    if tid:
        await event_bus.publish(
            Event(
                topic="channel.email.delivery",
                tenant_id=tid,
                payload={
                    "provider": provider,
                    "notification_type": notification_type,
                    "provider_message_id": message_id,
                    "raw_payload": payload,
                },
            )
        )

    return {
        "status": "ok",
        "notification_type": notification_type,
        "provider_message_id": message_id,
    }


# ---------------------------------------------------------------------------
# SMS delivery receipts
# ---------------------------------------------------------------------------

@router.post("/sms/{provider}")
async def sms_delivery_webhook(
    provider: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """Handle SMS delivery receipts from providers."""

    message_id = (
        payload.get("MessageSid")  # Twilio
        or payload.get("message_id")  # Generic
        or payload.get("id", "")
    )
    status = (
        payload.get("MessageStatus")  # Twilio
        or payload.get("status")  # Generic
        or "unknown"
    )

    logger.info(
        "SMS delivery receipt from %s: message_id=%s, status=%s",
        provider,
        message_id,
        status,
    )

    tenant_id_raw = payload.get("tenant_id")
    if tenant_id_raw:
        try:
            tid = UUID(str(tenant_id_raw))
        except (ValueError, AttributeError):
            tid = None
    else:
        tid = None

    if tid:
        await event_bus.publish(
            Event(
                topic="channel.sms.delivery",
                tenant_id=tid,
                payload={
                    "provider": provider,
                    "provider_message_id": message_id,
                    "status": status,
                    "raw_payload": payload,
                },
            )
        )

    return {"status": "ok", "provider_message_id": message_id, "delivery_status": status}
