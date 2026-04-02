"""Supervisor endpoints: live call Listen, Whisper, and Barge.

Listen  — real-time audio stream of caller + AI to supervisor browser
Whisper — inject guidance into the AI conversation (customer can't hear)
Barge   — mute AI, take over the call as a human agent
"""

import asyncio
import base64
import json
import logging
import uuid as _uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select

from app.config import settings
from app.core.handoff_engine import handoff_engine
from app.core.state_machine import Trigger
from app.db.engine import async_session_factory
from app.db.models.channel_session import ChannelSession
from app.livekit import session_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/supervisor", tags=["supervisor"])


# ---------------------------------------------------------------------------
# Listen — stream live call audio to supervisor browser
# ---------------------------------------------------------------------------


@router.websocket("/listen/{conv_id}")
async def supervisor_listen(ws: WebSocket, conv_id: str):
    """Stream live caller + AI audio to supervisor.

    Sends JSON frames: {"source": "caller"|"ai", "audio": "<base64 mulaw>"}
    Supervisor frontend decodes mulaw and plays via Web Audio API.
    """
    await ws.accept()
    logger.info("Supervisor listen connected: conv=%s", conv_id)

    handle = session_registry.get(conv_id)
    if not handle:
        await ws.send_json({"error": "No active session for this conversation"})
        await ws.close()
        return

    # Create a queue for this listener
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    handle.listeners.add(q)

    try:
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=30.0)
                await ws.send_json({
                    "source": item["source"],
                    "audio": base64.b64encode(item["audio"]).decode("ascii"),
                })
            except asyncio.TimeoutError:
                # Send keepalive ping
                await ws.send_json({"keepalive": True})
            except Exception:
                break
    except WebSocketDisconnect:
        logger.info("Supervisor listen disconnected: conv=%s", conv_id)
    except Exception:
        logger.exception("Error in supervisor listen: conv=%s", conv_id)
    finally:
        handle.listeners.discard(q)
        logger.info("Supervisor listener removed: conv=%s", conv_id)


# ---------------------------------------------------------------------------
# Whisper — inject supervisor guidance into AI conversation
# ---------------------------------------------------------------------------


class WhisperRequest(BaseModel):
    message: str


@router.post("/whisper/{conv_id}")
async def supervisor_whisper(conv_id: str, body: WhisperRequest):
    """Inject supervisor guidance into the AI conversation.

    The AI will incorporate this in its next response. The customer
    never hears this — it's injected as a system-level context hint.
    """
    handle = session_registry.get(conv_id)
    if not handle:
        raise HTTPException(404, "No active session for this conversation")

    session = handle.session
    session.inject_supervisor_hint(body.message)
    logger.info("Supervisor whisper injected: conv=%s, hint='%s'", conv_id, body.message[:80])

    return {"status": "ok", "message": "Hint injected — AI will incorporate in next response"}


# ---------------------------------------------------------------------------
# Barge — supervisor takes over the call from AI
# ---------------------------------------------------------------------------


@router.post("/barge/{conv_id}")
async def supervisor_barge(conv_id: str):
    """Supervisor takes over the call: stop AI, redirect to conference.

    1. Cancels any in-progress AI TTS/LLM
    2. Sends clearAudio to Plivo
    3. Transitions state to HUMAN_HANDLING
    4. Redirects call to conference room
    5. Returns conference name for supervisor to join via softphone
    """
    handle = session_registry.get(conv_id)
    if not handle:
        raise HTTPException(404, "No active session for this conversation")

    session = handle.session

    # 1. Cancel AI pipeline
    session._barge_in_event.set()
    session.finish_speaking()

    # 2. Send clearAudio to Plivo
    try:
        await handle.plivo_ws.send_json({
            "event": "clearAudio",
            "streamId": handle.stream_sid,
        })
        logger.info("Barge: sent clearAudio to Plivo for conv=%s", conv_id)
    except Exception:
        logger.warning("Barge: failed to send clearAudio for conv=%s", conv_id)

    # 3. State transitions + redirect call to conference
    conference_name = f"room-{conv_id}"
    async with async_session_factory() as db:
        conv_uuid = _uuid.UUID(conv_id)

        # Transition: AI_HANDLING -> QUEUED_FOR_HUMAN -> HUMAN_HANDLING
        for trigger in (Trigger.AI_TRANSFER, Trigger.AGENT_ASSIGNED):
            try:
                await handoff_engine.process_trigger(
                    db=db,
                    conversation_id=conv_uuid,
                    trigger=trigger,
                    metadata={"reason": "Supervisor barge-in", "handler": "supervisor"},
                )
            except Exception as exc:
                if "not allowed in state" in str(exc):
                    logger.info("Barge: skipping %s for conv=%s (already transitioned)", trigger.value, conv_id)
                else:
                    raise
        await db.commit()

        # 4. Redirect Plivo call to conference
        result = await db.execute(
            select(ChannelSession.provider_session_id)
            .where(ChannelSession.conversation_id == conv_uuid)
            .where(ChannelSession.provider == "plivo")
            .order_by(ChannelSession.created_at.desc())
            .limit(1)
        )
        call_uuid = result.scalar_one_or_none()

        if call_uuid:
            try:
                escalate_url = (
                    settings.base_webhook_url.rstrip("/")
                    + f"/api/v1/plivo/escalate-to-human"
                    + f"?tenant_id={session.tenant_id}&conv_id={conv_id}"
                )
                import plivo
                plivo_client = plivo.RestClient(settings.plivo_auth_id, settings.plivo_auth_token)
                await asyncio.to_thread(
                    lambda: plivo_client.calls.update(
                        call_uuid,
                        aleg_url=escalate_url,
                        aleg_method="POST",
                    )
                )
                logger.info("Barge: redirected call %s to conference for conv=%s", call_uuid, conv_id)
            except Exception:
                logger.exception("Barge: failed to redirect call for conv=%s", conv_id)

    return {
        "status": "ok",
        "conference_name": conference_name,
        "message": "AI muted. Call redirected to conference. Join via softphone.",
    }


# ---------------------------------------------------------------------------
# Active sessions list (for dashboard)
# ---------------------------------------------------------------------------


@router.get("/active-sessions")
async def list_active_sessions():
    """List all active AI voice sessions (for supervisor dashboard)."""
    sessions = []
    for conv_id in session_registry.list_active():
        handle = session_registry.get(conv_id)
        if handle:
            s = handle.session
            sessions.append({
                "conversation_id": conv_id,
                "tenant_id": s.tenant_id,
                "turn_count": s.turn_count,
                "language": s.language,
                "listener_count": len(handle.listeners),
            })
    return sessions
