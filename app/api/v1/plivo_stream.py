"""Plivo bidirectional audio stream WebSocket endpoint — LiveKit bridge path.

Receives raw mulaw audio from Plivo <Stream> and bridges it into a LiveKit
room. The LiveKit Agent worker (livekit_agent.py) handles STT -> LLM -> TTS.
"""

import asyncio
import base64
import json
import logging
import uuid as _uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from app.config import settings
from app.core.handoff_engine import handoff_engine
from app.core.state_machine import Trigger
from app.db.engine import async_session_factory
from app.db.models.tenant import Tenant
from app.voice_ai.plivo_livekit_bridge import PlivoLiveKitBridge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plivo", tags=["plivo-stream"])


async def _handle_stream_escalation(db, tenant_id: str, conv_id: str):
    """Trigger AI->Human escalation.

    The handoff engine sends a data channel message to the LiveKit room —
    the bridge stays connected and the AI agent disconnects gracefully.
    """
    conv_uuid = _uuid.UUID(conv_id)

    try:
        await handoff_engine.process_trigger(
            db=db,
            conversation_id=conv_uuid,
            trigger=Trigger.AI_TRANSFER,
            metadata={"reason": "AI escalation via voice stream", "provider": "plivo"},
        )
        await db.commit()
        logger.info("Escalation state transition complete: conv=%s", conv_id)
    except Exception:
        logger.exception("Failed to transition state for escalation: conv=%s", conv_id)
        return

    # LiveKit path: handoff engine already sent data channel message
    # to the room — no Plivo redirect needed. Bridge stays connected.
    logger.info("LiveKit escalation: bridge stays connected, AI agent will disconnect (conv=%s)", conv_id)


async def _handle_stream_hangup(db, tenant_id: str, conv_id: str):
    """End the call when the customer says goodbye."""
    conv_uuid = _uuid.UUID(conv_id)

    try:
        for trigger in (Trigger.AGENT_END, Trigger.DISPOSITION_SUBMITTED):
            try:
                await handoff_engine.process_trigger(
                    db=db,
                    conversation_id=conv_uuid,
                    trigger=trigger,
                    metadata={"reason": "Customer said goodbye", "disposition": "resolved"},
                )
            except Exception as exc:
                if "not allowed in state" in str(exc):
                    logger.info("Skipping %s for conv=%s (already transitioned)", trigger.value, conv_id)
                    break
                raise
        await db.commit()
        logger.info("Call ended by AI (customer goodbye): conv=%s", conv_id)
    except Exception:
        logger.exception("Failed to end call via AI: conv=%s", conv_id)


@router.websocket("/audio-stream")
async def plivo_audio_stream(
    ws: WebSocket,
    tenant_id: str = "",
    conv_id: str = "",
    language: str = "en",
    speaker: str = "ritu",
    skip_greeting: str = "",
):
    """Bidirectional audio stream from Plivo <Stream> — LiveKit bridge path."""
    await ws.accept()
    logger.info("Plivo audio stream connected: conv=%s, lang=%s", conv_id, language)
    await _handle_livekit_bridge(ws, tenant_id=tenant_id, conv_id=conv_id, language=language)


# ======================================================================
# LiveKit bridge path
# ======================================================================

async def _handle_livekit_bridge(
    ws: WebSocket,
    *,
    tenant_id: str,
    conv_id: str,
    language: str,
) -> None:
    """Handle a Plivo audio stream by bridging into a LiveKit room.

    The LiveKit Agent (livekit_agent.py) auto-joins the room and
    handles STT -> LLM -> TTS. This function just shuttles audio
    between Plivo and LiveKit.
    """
    # Fetch tenant name, custom AI prompt, and groq model for room metadata
    company_name = "Demo Corp"
    ai_system_prompt: str | None = None
    groq_model: str | None = None
    if tenant_id:
        try:
            async with async_session_factory() as db:
                tenant = (await db.execute(
                    select(Tenant).where(Tenant.id == _uuid.UUID(tenant_id))
                )).scalar_one_or_none()
                if tenant:
                    company_name = tenant.name
                    if tenant.config:
                        ai_system_prompt = tenant.config.get("ai_system_prompt")
                        groq_model = tenant.config.get("groq_model")
        except Exception:
            logger.warning("Failed to fetch tenant %s for LiveKit bridge", tenant_id)

    bridge = PlivoLiveKitBridge(
        conversation_id=conv_id,
        tenant_id=tenant_id,
        language=language,
        company_name=company_name,
        ai_system_prompt=ai_system_prompt,
        groq_model=groq_model,
        plivo_ws_send=ws.send_json,
    )

    try:
        await bridge.start()

        while True:
            # Race: next Plivo message vs. LiveKit room disconnect
            recv_task = asyncio.ensure_future(ws.receive_text())
            disc_task = asyncio.ensure_future(bridge.wait_until_disconnected())
            done, pending = await asyncio.wait(
                {recv_task, disc_task},
                timeout=60.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            if not done:
                logger.warning("Plivo stream timeout (LiveKit bridge): conv=%s", conv_id)
                break

            if disc_task in done:
                logger.info("LiveKit room disconnected — closing Plivo stream: conv=%s", conv_id)
                break

            try:
                data = recv_task.result()
            except Exception:
                break

            msg = json.loads(data)
            event_type = msg.get("event", "")

            if event_type == "start":
                start_data = msg.get("start", {})
                stream_sid = start_data.get("streamId", "") or start_data.get("streamSid", "")
                bridge.update_stream_sid(stream_sid)
                logger.info("LiveKit bridge stream started: sid=%s, room=%s", stream_sid, bridge.room_name)
                # Greeting is generated by the LLM via generate_reply() in livekit_agent.py

            elif event_type == "media":
                payload = msg.get("media", {}).get("payload", "")
                if payload:
                    audio_bytes = base64.b64decode(payload)
                    await bridge.feed_audio(audio_bytes)

            elif event_type == "stop":
                logger.info("LiveKit bridge stream stopped: conv=%s", conv_id)
                break

    except WebSocketDisconnect:
        logger.info("Plivo stream disconnected (LiveKit bridge): conv=%s", conv_id)
    except Exception:
        logger.exception("Error in LiveKit bridge: conv=%s", conv_id)
    finally:
        # Ensure bridge and WebSocket are fully cleaned up
        try:
            await bridge.stop()
        except Exception:
            logger.warning("Error stopping bridge for conv=%s", conv_id, exc_info=True)
        try:
            await ws.close()
        except Exception:
            pass  # WebSocket may already be closed
