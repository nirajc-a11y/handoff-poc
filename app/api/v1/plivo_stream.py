"""Plivo bidirectional audio stream WebSocket endpoint.

Receives raw mulaw audio from Plivo <Stream>, processes through
VoiceAISession (Sarvam STT -> Groq LLM -> Sarvam TTS), sends audio back.

Production features:
- Streaming greeting TTS (~500ms to first audio)
- Barge-in: clearAudio + cancel TTS when user interrupts
- Sentence-pipelined TTS via streaming LLM
"""

import asyncio
import base64
import json
import logging
import uuid as _uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from starlette.websockets import WebSocketState

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
            logger.warning("No ChannelSession found for conv=%s -- cannot redirect call", conv_id)
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
        # Each trigger is guarded — Plivo call-status webhook may race and
        # transition the conversation to ENDED before we get here.
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
    skip_greeting: str = "",  # kept for backward compat, now ignored
):
    """Bidirectional audio stream from Plivo <Stream>."""
    await ws.accept()
    logger.info("Plivo audio stream connected: conv=%s, lang=%s, speaker=%s", conv_id, language, speaker)

    session = VoiceAISession(
        tenant_id=tenant_id, conv_id=conv_id,
        language=language, speaker=speaker,
    )

    stream_started = False
    stream_sid = ""
    ws_open = True
    processing_lock = asyncio.Lock()

    # Track bytes sent during streaming TTS to calculate playback wait.
    # Sarvam generates audio faster than real-time, so Plivo buffers and
    # plays it back over a longer duration than we spend sending.
    _stream_bytes_sent = 0
    _stream_start_time = 0.0  # 0.0 = sentinel meaning "no chunk sent yet"
    _ECHO_BUFFER = 0.5  # Extra wait for phone-line echo round-trip (300-500ms)

    # ------------------------------------------------------------------
    # Audio send helpers
    # ------------------------------------------------------------------

    async def send_audio(mulaw_data: bytes):
        """Send mulaw audio back to Plivo in chunks."""
        nonlocal ws_open
        if not stream_started or not ws_open:
            return
        logger.info("Sending %d bytes of mulaw audio (%d chunks)", len(mulaw_data), len(mulaw_data) // 320 + 1)
        chunk_size = 320  # 20ms at 8kHz mulaw
        for i in range(0, len(mulaw_data), chunk_size):
            if not ws_open or session.barge_in_requested:
                break
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
                await asyncio.sleep(0.018)
            except Exception:
                ws_open = False
                break

    def _reset_stream_tracker():
        """Reset streaming playback tracker before a new TTS stream."""
        nonlocal _stream_bytes_sent, _stream_start_time
        _stream_bytes_sent = 0
        _stream_start_time = 0.0  # Will be set on first send_chunk call

    async def _wait_for_playback():
        """Wait for Plivo to finish playing buffered streaming audio.

        Streaming TTS sends chunks to Plivo faster than real-time (e.g.
        3.85s of audio generated in 1.3s). Plivo queues them and plays
        back at real-time speed. We must wait for that playback to end
        before calling finish_speaking(), otherwise the system hears
        its own voice as echo and transcribes it as phantom 'Yes'.

        Also adds an echo buffer (500ms) for phone-line round-trip delay.
        The wait is interruptible by barge-in.
        """
        if _stream_bytes_sent == 0 or _stream_start_time == 0.0:
            return
        playback_secs = _stream_bytes_sent / 8000
        elapsed = asyncio.get_event_loop().time() - _stream_start_time
        remaining = playback_secs - elapsed + _ECHO_BUFFER
        if remaining > 0:
            logger.info("Waiting %.1fs for Plivo playback to finish (%d bytes = %.1fs audio, sent in %.1fs, +%.1fs echo buffer)",
                        remaining, _stream_bytes_sent, playback_secs, elapsed, _ECHO_BUFFER)
            # Wait for playback OR barge-in, whichever comes first
            try:
                await asyncio.wait_for(session._barge_in_event.wait(), timeout=remaining)
                logger.info("Barge-in interrupted playback wait")
            except asyncio.TimeoutError:
                pass  # Normal: playback finished without interruption

    async def send_chunk(mulaw_chunk: bytes):
        """Send a single streaming TTS chunk to Plivo immediately."""
        nonlocal ws_open, _stream_bytes_sent, _stream_start_time
        if not stream_started or not ws_open:
            return
        try:
            await ws.send_json({
                "event": "playAudio",
                "streamId": stream_sid,
                "media": {
                    "contentType": "audio/x-mulaw",
                    "sampleRate": 8000,
                    "payload": base64.b64encode(mulaw_chunk).decode("ascii"),
                },
            })
            # Start timer on first chunk — not before STT/LLM processing
            if _stream_start_time == 0.0:
                _stream_start_time = asyncio.get_event_loop().time()
            _stream_bytes_sent += len(mulaw_chunk)
        except Exception:
            ws_open = False

    async def send_chunk_with_bargein(mulaw_chunk: bytes):
        """Send a streaming TTS chunk, but stop if barge-in detected."""
        if session.barge_in_requested:
            return
        await send_chunk(mulaw_chunk)

    async def send_clear_audio():
        """Tell Plivo to stop playing any queued audio (barge-in)."""
        nonlocal ws_open
        if not stream_started or not ws_open:
            return
        try:
            await ws.send_json({
                "event": "clearAudio",
                "streamId": stream_sid,
            })
            logger.info("Sent clearAudio to Plivo (barge-in)")
        except Exception:
            ws_open = False

    # ------------------------------------------------------------------
    # Turn processing
    # ------------------------------------------------------------------

    async def process_and_respond():
        nonlocal ws_open
        async with processing_lock:
            _reset_stream_tracker()
            turn_had_messages = False

            async with async_session_factory() as db:
                mulaw_response = await session.process_turn(db_session=db, on_audio=send_chunk_with_bargein)

                if session.barge_in_requested:
                    # User interrupted -- clear Plivo's audio buffer and resume listening
                    await send_clear_audio()
                    session.finish_speaking()
                    turn_had_messages = True
                    logger.info("Barge-in handled: cancelled TTS, resuming listening")
                elif mulaw_response == b"":
                    # Audio was streamed via on_audio callback.
                    # Wait for Plivo to finish playing buffered audio before listening.
                    await _wait_for_playback()
                    if session.barge_in_requested:
                        await send_clear_audio()
                    session.finish_speaking()
                    turn_had_messages = True
                elif mulaw_response and ws_open:
                    # Fallback: full TTS response -- send all at once
                    await send_audio(mulaw_response)
                    if session.barge_in_requested:
                        await send_clear_audio()
                        session.finish_speaking()
                    else:
                        playback_secs = len(mulaw_response) / 8000
                        send_secs = (len(mulaw_response) // 320 + 1) * 0.018
                        remaining = playback_secs - send_secs
                        if remaining > 0:
                            await asyncio.sleep(remaining)
                        session.finish_speaking()
                    turn_had_messages = True
                else:
                    # STT returned empty -- just reset
                    session.finish_speaking()

                await db.commit()

                # Notify frontend of new messages for ALL paths that saved data
                if turn_had_messages and conv_id and tenant_id:
                    await event_bus.publish(Event(
                        topic="conversation.message_added",
                        tenant_id=_uuid.UUID(tenant_id),
                        payload={"conversation_id": conv_id},
                    ))

                # After sending AI response, check if escalation or hangup is needed
                if session.should_escalate and conv_id and tenant_id:
                    await _handle_stream_escalation(db, tenant_id, conv_id)
                elif session.should_end_call and conv_id and tenant_id:
                    await _handle_stream_hangup(db, tenant_id, conv_id)

    # ------------------------------------------------------------------
    # WebSocket event loop
    # ------------------------------------------------------------------

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            event_type = msg.get("event", "")

            if event_type == "start":
                stream_started = True
                start_data = msg.get("start", {})
                stream_sid = start_data.get("streamId", "") or start_data.get("streamSid", "")
                logger.info("Stream started: sid=%s", stream_sid)

                # Stream greeting with low latency (~500ms to first audio)
                # Acquire processing_lock to prevent interleaved sends with turn processing
                async def _stream_greeting():
                    async with processing_lock:
                        _reset_stream_tracker()
                        await session.stream_greeting(send_chunk)
                        # Wait for Plivo to finish playing buffered greeting audio
                        await _wait_for_playback()
                        if session.barge_in_requested:
                            await send_clear_audio()
                        session.finish_speaking()
                asyncio.create_task(_stream_greeting())

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
        ws_open = False
        logger.info("Audio stream ended: conv=%s, turns=%d", conv_id, session.turn_count)
