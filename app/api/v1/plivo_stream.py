"""Plivo bidirectional audio stream WebSocket endpoint.

Receives raw mulaw audio from Plivo <Stream>, forwards to Deepgram for
real-time STT, processes through VoiceAISession (Groq LLM -> Sarvam TTS),
sends audio back.

Production features:
- Deepgram streaming STT: continuous transcription, no audio cropping
- MinWords barge-in: user can interrupt AI via real speech (not echo)
- Streaming greeting TTS (~500ms to first audio)
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
from app.db.models.tenant import Tenant
from app.voice_ai.voice_agent import VoiceAISession
from app.voice_ai import session_registry
from app.voice_ai.session_registry import SessionHandle
from app.voice_ai.plivo_livekit_bridge import PlivoLiveKitBridge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plivo", tags=["plivo-stream"])


async def _handle_stream_escalation(db, tenant_id: str, conv_id: str):
    """Trigger AI->Human escalation by redirecting the live Plivo call."""
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
                legs="aleg",
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
    """Bidirectional audio stream from Plivo <Stream>."""
    await ws.accept()
    logger.info("Plivo audio stream connected: conv=%s, lang=%s, speaker=%s", conv_id, language, speaker)

    # ---- LiveKit Agent path (feature-flagged) ----
    if settings.use_livekit_agent and settings.livekit_url:
        await _handle_livekit_bridge(ws, tenant_id=tenant_id, conv_id=conv_id, language=language)
        return

    # ---- Legacy VoiceAISession path ----

    # Fetch tenant name and AI prompt from DB
    tenant_name = "Demo Corp"
    tenant_system_prompt: str | None = None
    if tenant_id:
        try:
            async with async_session_factory() as db:
                tenant = (await db.execute(select(Tenant).where(Tenant.id == _uuid.UUID(tenant_id)))).scalar_one_or_none()
                if tenant:
                    tenant_name = tenant.name
                    if tenant.config:
                        tenant_system_prompt = tenant.config.get("ai_system_prompt")
        except Exception:
            logger.warning("Failed to fetch tenant %s, using defaults", tenant_id)

    session = VoiceAISession(
        tenant_id=tenant_id, conv_id=conv_id,
        language=language, speaker=speaker,
        tenant_name=tenant_name, system_prompt=tenant_system_prompt,
    )

    # Register session for supervisor listen/whisper/barge
    _handle = SessionHandle(session=session, plivo_ws=ws)
    if conv_id:
        session_registry.register(conv_id, _handle)

    stream_started = False
    stream_sid = ""
    ws_open = True
    processing_lock = asyncio.Lock()

    # Track bytes sent during streaming TTS to calculate playback wait
    _stream_bytes_sent = 0
    _stream_start_time = 0.0
    _ECHO_BUFFER = 0.5

    # ------------------------------------------------------------------
    # Audio send helpers
    # ------------------------------------------------------------------

    async def send_audio(mulaw_data: bytes):
        nonlocal ws_open
        if not stream_started or not ws_open:
            return
        chunk_size = 320
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
        nonlocal _stream_bytes_sent, _stream_start_time
        _stream_bytes_sent = 0
        _stream_start_time = 0.0

    async def _wait_for_playback():
        if _stream_bytes_sent == 0 or _stream_start_time == 0.0:
            return
        playback_secs = _stream_bytes_sent / 8000
        elapsed = asyncio.get_event_loop().time() - _stream_start_time
        remaining = playback_secs - elapsed + _ECHO_BUFFER
        if remaining > 0:
            logger.info("Waiting %.1fs for Plivo playback (%d bytes = %.1fs audio, sent in %.1fs)",
                        remaining, _stream_bytes_sent, playback_secs, elapsed)
            try:
                await asyncio.wait_for(session._barge_in_event.wait(), timeout=remaining)
                logger.info("Barge-in interrupted playback wait")
            except asyncio.TimeoutError:
                pass

    async def send_chunk(mulaw_chunk: bytes):
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
            if _stream_start_time == 0.0:
                _stream_start_time = asyncio.get_event_loop().time()
            _stream_bytes_sent += len(mulaw_chunk)
            if _handle.listeners:
                await _handle.forward_to_listeners(mulaw_chunk, "ai")
        except Exception:
            ws_open = False

    async def send_chunk_with_bargein(mulaw_chunk: bytes):
        if session.barge_in_requested:
            return
        await send_chunk(mulaw_chunk)

    async def send_clear_audio():
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
                try:
                    mulaw_response = await asyncio.wait_for(
                        session.process_turn(db_session=db, on_audio=send_chunk_with_bargein),
                        timeout=15.0,
                    )
                except asyncio.TimeoutError:
                    logger.error("process_turn timed out after 15s: conv=%s", conv_id)
                    session.reset_listening()
                    return
                except Exception:
                    logger.exception("Error in process_turn: conv=%s", conv_id)
                    session.reset_listening()
                    return

                if session.barge_in_requested:
                    await send_clear_audio()
                    session.reset_listening()
                    turn_had_messages = mulaw_response is not None
                    logger.info("Barge-in handled: cancelled TTS, ready for next turn")
                elif mulaw_response == b"":
                    await _wait_for_playback()
                    if session.barge_in_requested:
                        await send_clear_audio()
                    session.finish_speaking()
                    turn_had_messages = True
                elif mulaw_response and ws_open:
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
                    session.reset_listening()

                await db.commit()

                if turn_had_messages and conv_id and tenant_id:
                    await event_bus.publish(Event(
                        topic="conversation.message_added",
                        tenant_id=_uuid.UUID(tenant_id),
                        payload={"conversation_id": conv_id},
                    ))

                if session.should_escalate and conv_id and tenant_id:
                    await _handle_stream_escalation(db, tenant_id, conv_id)
                elif session.should_end_call and conv_id and tenant_id:
                    await _handle_stream_hangup(db, tenant_id, conv_id)

    # ------------------------------------------------------------------
    # Background task: watch for Deepgram turn signals
    # ------------------------------------------------------------------

    async def _turn_watcher():
        """Wait for Deepgram utterance_end events and trigger turn processing."""
        while ws_open:
            has_turn = await session.wait_for_turn(timeout=2.0)
            if not has_turn:
                continue
            # Wait for processing lock to be free (don't tight-loop)
            while processing_lock.locked() and ws_open:
                await asyncio.sleep(0.1)
            if ws_open and session._final_transcripts:
                session._pending_turn.clear()
                asyncio.create_task(process_and_respond())

    turn_watcher_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # WebSocket event loop
    # ------------------------------------------------------------------

    try:
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=60.0)
            except asyncio.TimeoutError:
                logger.warning("Plivo stream timeout (60s no data): conv=%s", conv_id)
                break
            msg = json.loads(data)
            event_type = msg.get("event", "")

            if event_type == "start":
                stream_started = True
                start_data = msg.get("start", {})
                stream_sid = start_data.get("streamId", "") or start_data.get("streamSid", "")
                _handle.stream_sid = stream_sid
                logger.info("Stream started: sid=%s", stream_sid)

                # Start Deepgram streaming STT
                await session.start_deepgram()

                # Start turn watcher for Deepgram-driven endpointing
                if session._use_streaming_stt:
                    turn_watcher_task = asyncio.create_task(_turn_watcher())

                # Stream greeting
                async def _stream_greeting():
                    async with processing_lock:
                        _reset_stream_tracker()
                        await session.stream_greeting(send_chunk)
                        await _wait_for_playback()
                        if session.barge_in_requested:
                            await send_clear_audio()
                        session.finish_speaking()
                asyncio.create_task(_stream_greeting())

            elif event_type == "media":
                payload = msg.get("media", {}).get("payload", "")
                if payload:
                    audio_bytes = base64.b64decode(payload)
                    # Forward caller audio to supervisor listeners
                    if _handle.listeners:
                        await _handle.forward_to_listeners(audio_bytes, "caller")
                    # Feed audio to session (Deepgram + VAD)
                    speech_pause = await session.add_audio(audio_bytes)
                    # For batch STT fallback (no Deepgram), use old trigger
                    if speech_pause and not session._use_streaming_stt:
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
        # Cleanup
        if turn_watcher_task and not turn_watcher_task.done():
            turn_watcher_task.cancel()
        await session.stop_deepgram()
        if conv_id:
            session_registry.unregister(conv_id)
        logger.info("Audio stream ended: conv=%s, turns=%d", conv_id, session.turn_count)


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
    # Fetch tenant name for room metadata
    company_name = "Demo Corp"
    if tenant_id:
        try:
            async with async_session_factory() as db:
                tenant = (await db.execute(
                    select(Tenant).where(Tenant.id == _uuid.UUID(tenant_id))
                )).scalar_one_or_none()
                if tenant:
                    company_name = tenant.name
        except Exception:
            logger.warning("Failed to fetch tenant %s for LiveKit bridge", tenant_id)

    bridge = PlivoLiveKitBridge(
        conversation_id=conv_id,
        tenant_id=tenant_id,
        language=language,
        company_name=company_name,
        plivo_ws_send=ws.send_json,
    )

    try:
        await bridge.start()

        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=60.0)
            except asyncio.TimeoutError:
                logger.warning("Plivo stream timeout (LiveKit bridge): conv=%s", conv_id)
                break

            msg = json.loads(data)
            event_type = msg.get("event", "")

            if event_type == "start":
                start_data = msg.get("start", {})
                stream_sid = start_data.get("streamId", "") or start_data.get("streamSid", "")
                bridge.update_stream_sid(stream_sid)
                logger.info("LiveKit bridge stream started: sid=%s, room=%s", stream_sid, bridge.room_name)
                # Stream greeting immediately — don't wait for agent to join
                asyncio.create_task(bridge.stream_greeting())

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
        await bridge.stop()
