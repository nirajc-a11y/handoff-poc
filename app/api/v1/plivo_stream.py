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
from app.db.engine import async_session_factory
from app.livekit.voice_agent import VoiceAISession
from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plivo", tags=["plivo-stream"])


@router.websocket("/audio-stream")
async def plivo_audio_stream(
    ws: WebSocket,
    tenant_id: str = "",
    conv_id: str = "",
    language: str = "en",
):
    """Bidirectional audio stream from Plivo <Stream>."""
    await ws.accept()
    logger.info("Plivo audio stream connected: conv=%s, lang=%s", conv_id, language)

    session = VoiceAISession(
        tenant_id=tenant_id, conv_id=conv_id,
        language=language, speaker="meera",
    )

    stream_sid = ""
    processing_lock = asyncio.Lock()

    async def send_audio(mulaw_data: bytes):
        nonlocal stream_sid
        if not stream_sid:
            return
        chunk_size = 320  # 20ms at 8kHz mulaw
        for i in range(0, len(mulaw_data), chunk_size):
            chunk = mulaw_data[i:i + chunk_size]
            try:
                await ws.send_json({
                    "event": "playAudio",
                    "media": {
                        "contentType": "audio/x-mulaw;rate=8000",
                        "sampleRate": 8000,
                        "payload": base64.b64encode(chunk).decode("ascii"),
                    },
                })
                await asyncio.sleep(0.02)
            except Exception:
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

    try:
        greeting_audio = await session.get_greeting_audio()

        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            event_type = msg.get("event", "")

            if event_type == "start":
                stream_sid = msg.get("start", {}).get("streamSid", "")
                logger.info("Stream started: sid=%s", stream_sid)
                if greeting_audio:
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
