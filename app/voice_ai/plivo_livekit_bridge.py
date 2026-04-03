"""Plivo-to-LiveKit audio bridge.

Receives mulaw audio from a Plivo bidirectional WebSocket stream,
converts to PCM, and publishes it as an audio track in a LiveKit room.
Subscribes to the LiveKit Agent's audio track and sends PCM->mulaw
back to Plivo via playAudio events.

IMPORTANT: Plivo's bidirectional <Stream> only delivers caller audio TO us.
Agent audio reaches the caller ONLY via playAudio events we send back.
LiveKit's WebRTC routing between room participants does NOT reach Plivo.

This module is used when settings.use_livekit_agent is True.
"""

from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging
from uuid import UUID

from livekit import api as lk_api, rtc

from app.config import settings
from app.voice_ai.sarvam import synthesize_stream


class _IgnoreLKSessionFilter(logging.Filter):
    """Suppress 'ignoring byte/text stream with topic lk.agent.session' spam."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "ignoring" not in msg or "lk.agent.session" not in msg


logging.getLogger().addFilter(_IgnoreLKSessionFilter())
logging.getLogger().addFilter(type("_F", (logging.Filter,), {
    "filter": staticmethod(lambda r: "lk.transcription" not in r.getMessage())
})())

logger = logging.getLogger(__name__)

# LiveKit expects specific frame sizes; 20ms at 24kHz mono 16-bit = 480 samples = 960 bytes
_LK_SAMPLE_RATE = 24000
_LK_FRAME_DURATION_MS = 20
_LK_SAMPLES_PER_FRAME = _LK_SAMPLE_RATE * _LK_FRAME_DURATION_MS // 1000  # 480
_LK_FRAME_BYTES = _LK_SAMPLES_PER_FRAME * 2  # 960 bytes (16-bit mono)

# Plivo sends 20ms at 8kHz mulaw = 160 bytes
_PLIVO_SAMPLE_RATE = 8000
_PLIVO_CHUNK_SIZE = 320  # 40ms at 8kHz mulaw — Plivo's preferred chunk size


class PlivoLiveKitBridge:
    """Bridges audio between a Plivo WebSocket and a LiveKit room.

    Audio paths:
      Caller -> Plivo WS -> feed_audio() -> mulaw->PCM 24kHz -> LiveKit room -> Agent STT
      Agent TTS -> LiveKit room -> _forward_agent_audio() -> PCM 8kHz->mulaw -> playAudio -> Plivo -> Caller

    The _forward_agent_audio path is CRITICAL — it's the only way agent audio
    reaches the caller. Without it, the caller hears silence after the greeting.
    """

    def __init__(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        language: str = "en",
        company_name: str = "Demo Corp",
        plivo_ws_send: ...,  # async callable to send JSON to Plivo WS
        stream_sid: str = "",
    ) -> None:
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.language = language
        self.company_name = company_name
        self._plivo_send = plivo_ws_send
        self._stream_sid = stream_sid

        self._room: rtc.Room | None = None
        self._audio_source: rtc.AudioSource | None = None
        self._pcm_buffer = bytearray()
        self._mulaw_out_buffer = bytearray()
        self._running = False
        self._subscribe_task: asyncio.Task | None = None
        self._agent_speaking = False  # Track if agent is currently sending audio

    @property
    def room_name(self) -> str:
        return f"room-{self.conversation_id}"

    async def start(self) -> None:
        """Create a LiveKit room, join as plivo-bridge, and start listening.

        Uses pre-warmed room if available (saves ~2.74s LiveKit dispatch delay).
        Falls back to creating room on the spot.
        """
        from app.services.room_prewarmer import room_prewarmer

        # 1. Try pre-warmed room first (created during IVR phase)
        prewarmed = room_prewarmer.consume(self.conversation_id)
        if prewarmed:
            logger.info("Using pre-warmed room %s (conv=%s)", prewarmed.room_name, self.conversation_id)
        else:
            # Fallback: create room on the spot (old path)
            logger.info("No pre-warmed room for conv=%s, creating on-demand", self.conversation_id)
            room_api = lk_api.LiveKitAPI(
                url=settings.livekit_url,
                api_key=settings.livekit_api_key,
                api_secret=settings.livekit_api_secret,
            )
            try:
                await room_api.room.create_room(
                    lk_api.CreateRoomRequest(
                        name=self.room_name,
                        metadata=json.dumps({
                            "tenant_id": self.tenant_id,
                            "conversation_id": self.conversation_id,
                            "language": self.language,
                            "company_name": self.company_name,
                        }),
                    )
                )
            except Exception as exc:
                exc_str = str(exc).lower()
                if "already exists" in exc_str or "already_exists" in exc_str:
                    logger.debug("Room %s already exists, continuing", self.room_name)
                else:
                    logger.error("Failed to create LiveKit room %s: %s", self.room_name, exc)
                    raise
            finally:
                await room_api.aclose()

        # 2. Generate access token for plivo-bridge participant
        token = lk_api.AccessToken(
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        token.with_identity("plivo-bridge")
        token.with_name("Plivo Audio Bridge")
        token.with_grants(
            lk_api.VideoGrants(
                room_join=True,
                room=self.room_name,
                can_publish=True,
                can_subscribe=True,
            )
        )
        jwt_token = token.to_jwt()

        # 3. Connect to room
        self._room = rtc.Room()

        # Subscribe to agent audio tracks — this is how agent audio reaches the caller
        @self._room.on("track_subscribed")
        def _on_track(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity != "plivo-bridge":
                logger.info("Subscribed to agent audio track from %s", participant.identity)
                # Request audio at 8kHz mono to match Plivo format
                audio_stream = rtc.AudioStream(
                    track, sample_rate=_PLIVO_SAMPLE_RATE, num_channels=1
                )
                self._subscribe_task = asyncio.create_task(
                    self._forward_agent_audio(audio_stream)
                )

        await self._room.connect(settings.livekit_url, jwt_token)

        # 4. Create and publish caller audio track as MICROPHONE source
        self._audio_source = rtc.AudioSource(sample_rate=_LK_SAMPLE_RATE, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("caller-audio", self._audio_source)
        publish_opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await self._room.local_participant.publish_track(track, publish_opts)

        self._running = True
        logger.info("PlivoLiveKitBridge started: room=%s", self.room_name)

    # ------------------------------------------------------------------
    # Greeting — sent directly to Plivo, bypasses LiveKit agent
    # ------------------------------------------------------------------

    async def stream_greeting(self) -> None:
        """Stream a TTS greeting directly to Plivo — plays immediately
        without waiting for the LiveKit Agent to join the room.

        Uses Redis-cached greeting if available (0ms vs ~1.08s live TTS).
        Falls back to live Sarvam synthesis.
        """
        if not self._stream_sid:
            logger.warning("Cannot stream greeting: no stream_sid yet")
            return

        # --- Try Redis-cached greeting first (saves ~1.08s) ---
        try:
            from app.services.greeting_cache import get_cached_greeting
            from app.core.redis import get_redis

            redis = get_redis()
            cached = await get_cached_greeting(redis, self.tenant_id, self.language, self.company_name)
            if cached:
                logger.info("Playing cached greeting (%d bytes) for room=%s", len(cached), self.room_name)
                await self._send_mulaw_to_plivo(cached)
                return
        except Exception:
            logger.warning("Failed to check greeting cache, falling back to live TTS", exc_info=True)

        # --- Fallback: live Sarvam TTS synthesis ---
        if self.language == "mr":
            text = f"नमस्कार! {self.company_name} मध्ये आपले स्वागत आहे. मी माया, तुमची AI सहाय्यक. कृपया थांबा, मी तुमच्याशी लवकरच बोलते."
        else:
            text = f"Hello! Welcome to {self.company_name}. I'm Maya, your AI assistant. Please hold on while I connect."

        logger.info("Streaming live greeting to Plivo for room=%s", self.room_name)
        try:
            chunks_for_cache: list[bytes] = []
            async for mulaw_chunk in synthesize_stream(
                text=text,
                language=self.language,
                speaker="ritu",
            ):
                if not self._running:
                    break
                await self._plivo_send({
                    "event": "playAudio",
                    "streamId": self._stream_sid,
                    "media": {
                        "contentType": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "payload": base64.b64encode(mulaw_chunk).decode("ascii"),
                    },
                })
                chunks_for_cache.append(mulaw_chunk)

            # Cache for next time (background, non-blocking)
            if chunks_for_cache:
                try:
                    from app.services.greeting_cache import cache_greeting
                    from app.core.redis import get_redis
                    redis = get_redis()
                    full_audio = b"".join(chunks_for_cache)
                    asyncio.create_task(
                        cache_greeting(redis, self.tenant_id, self.language, self.company_name, full_audio)
                    )
                except Exception:
                    pass  # non-fatal
        except Exception:
            logger.exception("Failed to stream greeting for room=%s", self.room_name)

    async def _send_mulaw_to_plivo(self, audio_bytes: bytes) -> None:
        """Send mulaw audio to Plivo in fixed-size chunks."""
        offset = 0
        while offset < len(audio_bytes) and self._running:
            chunk = audio_bytes[offset:offset + _PLIVO_CHUNK_SIZE]
            await self._plivo_send({
                "event": "playAudio",
                "streamId": self._stream_sid,
                "media": {
                    "contentType": "audio/x-mulaw",
                    "sampleRate": 8000,
                    "payload": base64.b64encode(chunk).decode("ascii"),
                },
            })
            offset += _PLIVO_CHUNK_SIZE

    # ------------------------------------------------------------------
    # Caller audio IN: Plivo -> LiveKit room
    # ------------------------------------------------------------------

    async def feed_audio(self, mulaw_bytes: bytes) -> None:
        """Feed mulaw audio from Plivo into the LiveKit room.

        Converts mulaw 8kHz -> PCM 16-bit 24kHz and publishes as audio frames.
        """
        if not self._running or not self._audio_source:
            return

        # mulaw -> PCM 16-bit at 8kHz
        pcm_8k = audioop.ulaw2lin(mulaw_bytes, 2)
        # Upsample 8kHz -> 24kHz
        pcm_24k, _ = audioop.ratecv(pcm_8k, 2, 1, _PLIVO_SAMPLE_RATE, _LK_SAMPLE_RATE, None)

        # Buffer PCM and emit complete frames
        self._pcm_buffer.extend(pcm_24k)
        while len(self._pcm_buffer) >= _LK_FRAME_BYTES:
            frame_data = bytes(self._pcm_buffer[:_LK_FRAME_BYTES])
            self._pcm_buffer = self._pcm_buffer[_LK_FRAME_BYTES:]

            frame = rtc.AudioFrame(
                data=frame_data,
                sample_rate=_LK_SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=_LK_SAMPLES_PER_FRAME,
            )
            await self._audio_source.capture_frame(frame)

    # ------------------------------------------------------------------
    # Agent audio OUT: LiveKit room -> Plivo (THE CRITICAL PATH)
    # ------------------------------------------------------------------

    async def _forward_agent_audio(self, audio_stream: rtc.AudioStream) -> None:
        """Forward agent's audio track from LiveKit to Plivo via playAudio.

        This is the ONLY path for agent audio to reach the caller.
        Plivo's bidirectional stream only delivers caller audio TO us;
        we must send agent audio BACK via playAudio events.

        Audio arrives as PCM 16-bit 8kHz (resampled by LiveKit's AudioStream).
        We convert to mulaw and send in 320-byte chunks (40ms at 8kHz).
        """
        chunks_sent = 0
        frames_received = 0
        empty_frames = 0

        logger.info(
            "Agent audio forwarding started: conv=%s, stream_sid=%s",
            self.conversation_id, self._stream_sid,
        )

        try:
            async for event in audio_stream:
                if not self._running:
                    logger.info("Agent audio forwarding: bridge stopped, exiting")
                    break

                frame: rtc.AudioFrame = event.frame
                pcm_data = bytes(frame.data)
                frames_received += 1

                # Log first few frames for debugging
                if frames_received <= 5:
                    rms = audioop.rms(pcm_data, 2) if pcm_data else 0
                    logger.info(
                        "Agent audio frame #%d: %d bytes, rms=%d, sample_rate=%d, channels=%d, samples=%d",
                        frames_received, len(pcm_data), rms,
                        frame.sample_rate, frame.num_channels, frame.samples_per_channel,
                    )
                elif frames_received == 6:
                    logger.info("Agent audio: suppressing per-frame logs after frame 5")

                if not pcm_data:
                    empty_frames += 1
                    continue

                # Convert PCM 16-bit 8kHz -> mulaw 8kHz
                try:
                    mulaw_data = audioop.lin2ulaw(pcm_data, 2)
                except audioop.error as e:
                    if frames_received <= 5:
                        logger.warning("audioop.lin2ulaw failed on frame #%d: %s", frames_received, e)
                    continue

                self._mulaw_out_buffer.extend(mulaw_data)

                # Send buffered chunks to Plivo
                while len(self._mulaw_out_buffer) >= _PLIVO_CHUNK_SIZE:
                    chunk = bytes(self._mulaw_out_buffer[:_PLIVO_CHUNK_SIZE])
                    self._mulaw_out_buffer = self._mulaw_out_buffer[_PLIVO_CHUNK_SIZE:]
                    try:
                        await self._plivo_send({
                            "event": "playAudio",
                            "streamId": self._stream_sid,
                            "media": {
                                "contentType": "audio/x-mulaw",
                                "sampleRate": 8000,
                                "payload": base64.b64encode(chunk).decode("ascii"),
                            },
                        })
                        chunks_sent += 1
                        if chunks_sent == 1:
                            logger.info(
                                "First agent audio chunk sent to Plivo (%d bytes, after %d frames)",
                                _PLIVO_CHUNK_SIZE, frames_received,
                            )
                    except Exception:
                        logger.error(
                            "Failed to send agent audio to Plivo (chunk #%d), stopping bridge",
                            chunks_sent,
                        )
                        self._running = False
                        return

            # Flush remaining buffer
            if self._mulaw_out_buffer and self._running:
                try:
                    await self._plivo_send({
                        "event": "playAudio",
                        "streamId": self._stream_sid,
                        "media": {
                            "contentType": "audio/x-mulaw",
                            "sampleRate": 8000,
                            "payload": base64.b64encode(bytes(self._mulaw_out_buffer)).decode("ascii"),
                        },
                    })
                    chunks_sent += 1
                except Exception:
                    pass
                self._mulaw_out_buffer.clear()

        except asyncio.CancelledError:
            pass
        except (ConnectionError, OSError) as exc:
            logger.warning("Agent audio forwarding lost connection: %s", exc)
        except Exception:
            logger.exception("Unexpected error forwarding agent audio to Plivo")
        finally:
            logger.info(
                "Agent audio forwarding ended: %d chunks sent, %d frames received, %d empty (conv=%s)",
                chunks_sent, frames_received, empty_frames, self.conversation_id,
            )

    # ------------------------------------------------------------------
    # Interruption support: clear agent audio when caller speaks
    # ------------------------------------------------------------------

    async def clear_agent_audio(self) -> None:
        """Send clearAudio to Plivo to stop any queued agent audio.

        Called when the caller interrupts (barge-in detected by the agent's VAD).
        """
        if not self._stream_sid or not self._running:
            return
        try:
            await self._plivo_send({
                "event": "clearAudio",
                "streamId": self._stream_sid,
            })
            self._mulaw_out_buffer.clear()
            logger.info("Cleared agent audio on Plivo (interruption): conv=%s", self.conversation_id)
        except Exception:
            logger.warning("Failed to send clearAudio to Plivo", exc_info=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def update_stream_sid(self, stream_sid: str) -> None:
        """Update the Plivo stream SID (received on 'start' event)."""
        self._stream_sid = stream_sid

    async def stop(self) -> None:
        """Leave the LiveKit room and clean up."""
        self._running = False
        if self._subscribe_task and not self._subscribe_task.done():
            self._subscribe_task.cancel()
            try:
                await self._subscribe_task
            except asyncio.CancelledError:
                pass
        if self._room:
            await self._room.disconnect()
            self._room = None
        self._audio_source = None
        self._pcm_buffer.clear()
        self._mulaw_out_buffer.clear()
        logger.info("PlivoLiveKitBridge stopped: room=%s", self.room_name)
