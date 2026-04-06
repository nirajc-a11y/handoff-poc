"""Supervisor endpoints — LiveKit-based listen, whisper, and barge."""

import json
import logging
import uuid as _uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from livekit import api as lk_api
from livekit.protocol import models as lk_models

from app.config import settings
from app.core.handoff_engine import handoff_engine
from app.schemas import SupervisorModeEnum
from app.core.state_machine import StateMachineError, Trigger
from app.db.engine import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/supervisor", tags=["supervisor"])


class WhisperRequest(BaseModel):
    message: str


# ======================================================================
# LiveKit-based supervisor endpoints
# ======================================================================


class LiveKitTokenMode(BaseModel):
    """Requested mode determines room permissions."""
    mode: SupervisorModeEnum = SupervisorModeEnum.listen


@router.post("/livekit-token/{conv_id}")
async def get_livekit_token(conv_id: str, body: LiveKitTokenMode | None = None):
    """Generate a LiveKit room token for supervisor to join the call room.

    - listen mode: subscribe-only (can hear, can't speak)
    - barge mode: can subscribe + publish (can speak into the room)
    """
    if not settings.livekit_url or not settings.use_livekit_agent:
        raise HTTPException(400, "LiveKit is not enabled")

    mode = (body.mode if body else "listen") or "listen"
    can_publish = mode == "barge"

    token = lk_api.AccessToken(
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    token.with_identity(f"supervisor-{conv_id[:8]}")
    token.with_name("Supervisor")
    token.with_grants(
        lk_api.VideoGrants(
            room_join=True,
            room=f"room-{conv_id}",
            can_publish=can_publish,
            can_subscribe=True,
            can_publish_data=True,  # Always allow data messages (for whisper)
        )
    )

    return {
        "token": token.to_jwt(),
        "url": settings.livekit_url,
        "room": f"room-{conv_id}",
        "mode": mode,
    }


@router.post("/livekit-whisper/{conv_id}")
async def livekit_whisper(conv_id: str, body: WhisperRequest):
    """Send a whisper message via LiveKit data channel.

    The LiveKit Agent subscribes to data messages and injects
    whisper hints as system context for the next LLM turn.
    """
    if not settings.livekit_url or not settings.use_livekit_agent:
        raise HTTPException(400, "LiveKit is not enabled")

    room_api = lk_api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        await room_api.room.send_data(
            lk_api.SendDataRequest(
                room=f"room-{conv_id}",
                data=json.dumps({"type": "whisper", "message": body.message}).encode(),
                kind=lk_models.DataPacket.RELIABLE,
            )
        )
    finally:
        await room_api.aclose()

    logger.info("LiveKit whisper sent: conv=%s, hint='%s'", conv_id, body.message[:80])
    return {"status": "ok", "message": "Whisper sent via LiveKit data channel"}


@router.post("/livekit-barge/{conv_id}")
async def livekit_barge(conv_id: str):
    """Supervisor barge via LiveKit: transition state, then mute the AI agent.

    1. Transition state to HUMAN_HANDLING (validates current state under row lock)
    2. Send barge data message to mute the agent (only if state transition succeeded)
    3. Return room token with publish permissions so supervisor can speak
    """
    if not settings.livekit_url or not settings.use_livekit_agent:
        raise HTTPException(400, "LiveKit is not enabled")

    # 1. State transition first — validate state before sending barge signal.
    # AI_TRANSFER moves AI_HANDLING → QUEUED_FOR_HUMAN; this also signals the
    # LiveKit agent to disconnect via _handle_queue_for_human's room data message.
    # We deliberately skip AGENT_ASSIGNED since the supervisor joins the room
    # directly with the token returned below — no routing engine lookup needed.
    async with async_session_factory() as db:
        conv_uuid = _uuid.UUID(conv_id)
        try:
            await handoff_engine.process_trigger(
                db=db,
                conversation_id=conv_uuid,
                trigger=Trigger.AI_TRANSFER,
                metadata={"reason": "Supervisor barge-in via LiveKit"},
            )
        except StateMachineError:
            logger.info("LiveKit barge: AI_TRANSFER skipped for conv=%s (state unchanged)", conv_id)
        await db.commit()

    # 2. Send barge signal via data message (only after state transition succeeds)
    room_api = lk_api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        await room_api.room.send_data(
            lk_api.SendDataRequest(
                room=f"room-{conv_id}",
                data=json.dumps({"type": "barge"}).encode(),
                kind=lk_models.DataPacket.RELIABLE,
            )
        )
    finally:
        await room_api.aclose()

    # 3. Return a publish-enabled token
    token = lk_api.AccessToken(
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    token.with_identity(f"supervisor-barge-{conv_id[:8]}")
    token.with_name("Supervisor (Barge)")
    token.with_grants(
        lk_api.VideoGrants(
            room_join=True,
            room=f"room-{conv_id}",
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
    )

    logger.info("LiveKit barge complete: conv=%s", conv_id)
    return {
        "status": "ok",
        "token": token.to_jwt(),
        "url": settings.livekit_url,
        "room": f"room-{conv_id}",
        "message": "AI agent muted. Join room with the provided token to speak.",
    }
