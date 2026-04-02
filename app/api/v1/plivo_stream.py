"""Plivo bidirectional audio stream WebSocket endpoint.

Receives raw mulaw audio from Plivo <Stream>, processes through
VoiceAISession (Sarvam STT -> Groq LLM -> Sarvam TTS), sends audio back.
"""

import asyncio
import base64
import json
import logging
import uuid as _uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.config import settings
from app.core.events import Event, event_bus
from app.core.handoff_engine import handoff_engine
from app.core.state_machine import Trigger
from app.db.engine import async_session_factory
from app.db.models.channel_session import ChannelSession
from app.livekit.voice_agent import VoiceAISession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plivo", tags=["plivo-stream"])


async def _handle_stream_escalation(db, tenant_id: str, conv_id: str):
    """Trigger AI->Human escalation by redirecting the live Plivo call."""
    conv_uuid = _uuid.UUID(conv_id)

    # 1. State machine transition
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

    # 2. Redirect the Plivo call to the escalate-to-human endpoint
    try:
        result = await db.execute(
            select(ChannelSession.provider_session_id)
            .where(ChannelSession.conversation_id == conv_uuid)
            .where(ChannelSession.provider == "plivo")
            .order_by(ChannelSession.created_at.desc())
            .limit(1)
        )
        call_uuid = result.scalar_one_or_none()

        if not call_uuid:
            logger.warning("No ChannelSession found for conv=%s — cannot redirect call", conv_id)
            return

        escalate_url = (
            settings.base_webhook_url.rstrip("/")
            + f"/api/v1/plivo/escalate-to-human"
            + f"?tenant_id={tenant_id}&conv_id={conv_id}"
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
        logger.info("Redirected call %s to escalation URL for conv=%s", call_uuid, conv_id)
    except Exception:
        logger.exception("Failed to redirect call for escalation: conv=%s", conv_id)


async def _handle_stream_hangup(db, tenant_id: str, conv_id: str):
    """End the call when the customer says goodbye."""
    conv_uuid = _uuid.UUID(conv_id)

    try:
        # Transition: AI_HANDLING -> WRAP_UP -> ENDED
        await handoff_engine.process_trigger(
            db=db,
            conversation_id=conv_uuid,
            trigger=Trigger.AGENT_END,
            metadata={"reason": "Customer said goodbye", "disposition": "resolved"},
        )
        await handoff_engine.process_trigger(
            db=db,
            conversation_id=conv_uuid,
            trigger=Trigger.DISPOSITION_SUBMITTED,
            metadata={"disposition": "resolved"},
        )
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
    """Bidirectional audio stream from Plivo <Stream>."""
    await ws.accept()
    print(f"\n>>> WEBSOCKET CONNECTED: conv={conv_id}, lang={language}, speaker={speaker}, skip_greeting={skip_greeting}")
    logger.info("Plivo audio stream connected: conv=%s, lang=%s, speaker=%s", conv_id, language, speaker)

    session = VoiceAISession(
        tenant_id=tenant_id, conv_id=conv_id,
        language=language, speaker=speaker,
    )

    stream_started = False
    stream_sid = ""
    processing_lock = asyncio.Lock()

    async def send_audio(mulaw_data: bytes):
        if not stream_started:
            logger.warning("send_audio called but stream not started yet, buffering skipped")
            return
        logger.info("Sending %d bytes of mulaw audio (%d chunks)", len(mulaw_data), len(mulaw_data) // 320 + 1)
        chunk_size = 320  # 20ms at 8kHz mulaw
        for i in range(0, len(mulaw_data), chunk_size):
            chunk = mulaw_data[i:i + chunk_size]
            try:
                await ws.send_json({
                    "event": "playAudio",
                    "streamId": stream_sid,
                    "media": {
                        "contentType": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "payload": base64.b64encode(chunk).decode("ascii"),
                    },
                })
                await asyncio.sleep(0.02)
            except Exception:
                logger.exception("Error sending audio chunk")
                break

    async def process_and_respond():
        async with processing_lock:
            async with async_session_factory() as db:
                mulaw_response = await session.process_turn(db_session=db)
                if mulaw_response:
                    await send_audio(mulaw_response)
                    if conv_id and tenant_id:
                        await event_bus.publish(Event(
                            topic="conversation.message_added",
                            tenant_id=_uuid.UUID(tenant_id),
                            payload={"conversation_id": conv_id},
                        ))
                await db.commit()

                # After sending AI response, check if escalation or hangup is needed
                if session.should_escalate and conv_id and tenant_id:
                    await _handle_stream_escalation(db, tenant_id, conv_id)
                elif session.should_end_call and conv_id and tenant_id:
                    await _handle_stream_hangup(db, tenant_id, conv_id)

    try:
        if skip_greeting.lower() in ("true", "1"):
            greeting_audio = None
            logger.info("Skipping Sarvam greeting — Plivo <Speak> already played")
        else:
            greeting_audio = await session.get_greeting_audio()
            logger.info("Greeting audio: %s", f"{len(greeting_audio)} bytes" if greeting_audio else "NONE (TTS failed)")

        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            event_type = msg.get("event", "")

            if event_type == "start":
                stream_started = True
                start_data = msg.get("start", {})
                # Plivo uses "streamId", Twilio uses "streamSid"
                stream_sid = start_data.get("streamId", "") or start_data.get("streamSid", "")
                print(f">>> STREAM STARTED: sid={stream_sid}")
                logger.info("Stream started: sid=%s, keys=%s", stream_sid, list(start_data.keys()))
                if greeting_audio:
                    print(f">>> SENDING GREETING: {len(greeting_audio)} bytes")
                    await send_audio(greeting_audio)

            elif event_type == "media":
                payload = msg.get("media", {}).get("payload", "")
                if payload:
                    audio_bytes = base64.b64decode(payload)
                    speech_pause = session.add_audio(audio_bytes)
                    if speech_pause:
                        asyncio.create_task(process_and_respond())

            elif event_type == "stop":
                logger.info("Stream stopped")
                break

    except WebSocketDisconnect:
        logger.info("Plivo audio stream disconnected: conv=%s", conv_id)
    except Exception:
        logger.exception("Error in Plivo audio stream")
    finally:
        logger.info("Audio stream ended: conv=%s, turns=%d", conv_id, session.turn_count)
