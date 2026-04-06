"""Plivo-to-LiveKit audio bridge.

Receives mulaw audio from a Plivo bidirectional WebSocket stream,
converts to PCM, and publishes it as an audio track in a LiveKit room.
Subscribes to room participants' audio tracks and sends PCM->mulaw
back to Plivo via playAudio events.

IMPORTANT: Plivo's bidirectional <Stream> only delivers caller audio TO us.
Agent audio reaches the caller ONLY via playAudio events we send back.
LiveKit's WebRTC routing between room participants does NOT reach Plivo.

Supports multiple participants (AI agent, human agent, supervisor barge)
with automatic track subscription/unsubscription as participants join/leave.

Barge-in (two layers for lowest latency):
  1. Bridge-level: feed_audio() monitors caller RMS energy. When caller
     speaks loudly enough during agent playback, instantly pauses outbound
     audio and sends clearAudio — zero round-trip delay.
  2. Agent-level: data channel {"type": "barge_in"} from the LiveKit agent
     as a confirmation/fallback.

Hold: Listens for {"type": "hold"} / {"type": "unhold"} data messages
to pause/resume audio forwarding from participants to Plivo.

This module is used when settings.use_livekit_agent is True.
"""

from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging
import time
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

# Plivo audio format
_PLIVO_SAMPLE_RATE = 8000
_PLIVO_CHUNK_SIZE = 160  # 20ms at 8kHz mulaw — smaller for lower latency

# Bounded buffer limits to prevent latency accumulation
_PCM_BUFFER_MAX = 4800   # 100ms at 24kHz 16-bit mono
_MULAW_BUFFER_MAX = 1600  # 200ms at 8kHz mulaw


class PlivoLiveKitBridge:
    """Bridges audio between a Plivo WebSocket and a LiveKit room.

    Audio paths:
      Caller -> Plivo WS -> feed_audio() -> mulaw->PCM 24kHz -> LiveKit room -> Agent STT
      Agent TTS -> LiveKit room -> _forward_participant_audio() -> PCM 8kHz->mulaw -> playAudio -> Plivo -> Caller

    Supports multiple concurrent participants. When the AI agent disconnects
    and a human agent joins, the bridge automatically subscribes to the new
    participant's audio track — no manual "switch" needed.
    """

    def __init__(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        language: str = "en",
        company_name: str = "Demo Corp",
        ai_system_prompt: str | None = None,
        groq_model: str | None = None,
        plivo_ws_send: ...,  # async callable to send JSON to Plivo WS
        stream_sid: str = "",
    ) -> None:
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.language = language
        self.company_name = company_name
        self.ai_system_prompt = ai_system_prompt
        self.groq_model = groq_model
        self._plivo_send = plivo_ws_send
        self._stream_sid = stream_sid

        self._room: rtc.Room | None = None
        self._audio_source: rtc.AudioSource | None = None
        self._pcm_buffer = bytearray()
        self._running = False

        # Multi-participant: one forwarding task per participant identity
        self._subscribe_tasks: dict[str, asyncio.Task] = {}

        # Hold state: pause audio forwarding to Plivo
        self._hold_active = False

        # Barge-in debounce: skip clearAudio if fired within this window
        self._last_barge_in_time: float = 0.0
        self._barge_in_debounce_s: float = 0.3

        # Overflow tracking for buffer overflow logging
        self._overflow_count = 0

        # Signals when the LiveKit room disconnects (used by the Plivo WS loop to exit)
        self._disconnected = asyncio.Event()

    async def wait_until_disconnected(self) -> None:
        """Await until the LiveKit room disconnects."""
        await self._disconnected.wait()

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
                room_metadata = {
                    "tenant_id": self.tenant_id,
                    "conversation_id": self.conversation_id,
                    "language": self.language,
                    "company_name": self.company_name,
                }
                if self.ai_system_prompt:
                    room_metadata["ai_system_prompt"] = self.ai_system_prompt
                if self.groq_model:
                    room_metadata["groq_model"] = self.groq_model
                await room_api.room.create_room(
                    lk_api.CreateRoomRequest(
                        name=self.room_name,
                        metadata=json.dumps(room_metadata),
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

        @self._room.on("disconnected")
        def _on_room_disconnected(*_):
            self._running = False
            self._disconnected.set()

        # Subscribe to audio tracks from any non-bridge participant
        @self._room.on("track_subscribed")
        def _on_track_subscribed(track, publication, participant):
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            identity = participant.identity
            # Skip our own tracks
            if identity == "plivo-bridge":
                return
            # Skip listen-only supervisors (they subscribe but don't publish audio we need)
            if identity.startswith("supervisor-") and not identity.startswith("supervisor-barge-"):
                logger.info("Skipping audio from listen-only supervisor %s", identity)
                return
            # Cancel existing task for this participant if any (e.g. track replaced)
            if identity in self._subscribe_tasks:
                self._subscribe_tasks[identity].cancel()
            logger.info("Subscribed to audio track from %s in room %s", identity, self.room_name)
            # Receive at native 24kHz — we downsample to 8kHz ourselves inside
            # _forward_participant_audio using audioop.ratecv with state, which
            # avoids frame-boundary discontinuities from LiveKit's internal resampler.
            audio_stream = rtc.AudioStream(
                track, sample_rate=_LK_SAMPLE_RATE, num_channels=1
            )
            self._subscribe_tasks[identity] = asyncio.create_task(
                self._forward_participant_audio(audio_stream, identity)
            )

        @self._room.on("track_unsubscribed")
        def _on_track_unsubscribed(track, publication, participant):
            identity = participant.identity
            task = self._subscribe_tasks.pop(identity, None)
            if task and not task.done():
                task.cancel()
                logger.info("Cancelled audio forwarding for %s (track unsubscribed)", identity)

        @self._room.on("participant_disconnected")
        def _on_participant_disconnected(participant):
            identity = participant.identity
            task = self._subscribe_tasks.pop(identity, None)
            if task and not task.done():
                task.cancel()
                logger.info("Cancelled audio forwarding for %s (participant left)", identity)

        # Listen for data messages: barge-in, hold, unhold
        @self._room.on("data_received")
        def _on_data(packet: rtc.DataPacket):
            try:
                raw = packet.data
                payload = raw if isinstance(raw, bytes) else raw.encode()
                msg = json.loads(payload)
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                return

            msg_type = msg.get("type")
            if msg_type == "barge_in":
                now = time.monotonic()
                if now - self._last_barge_in_time < self._barge_in_debounce_s:
                    return  # skip duplicate barge-in within debounce window
                self._last_barge_in_time = now
                asyncio.create_task(self.clear_agent_audio())
            elif msg_type == "hold":
                self._hold_active = True
                logger.info("Hold activated for conv=%s", self.conversation_id)
            elif msg_type == "unhold":
                self._hold_active = False
                logger.info("Hold deactivated for conv=%s", self.conversation_id)

        # Set _running BEFORE connect — the track_subscribed handler may fire
        # during connect() if the agent is already in the pre-warmed room,
        # and _forward_participant_audio checks this flag on every iteration.
        self._running = True

        await self._room.connect(settings.livekit_url, jwt_token)

        # 4. Create and publish caller audio track as MICROPHONE source
        self._audio_source = rtc.AudioSource(sample_rate=_LK_SAMPLE_RATE, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("caller-audio", self._audio_source)
        publish_opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await self._room.local_participant.publish_track(track, publish_opts)
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
        Barge-in is handled solely by the LiveKit agent's adaptive interruption
        detector — no bridge-level VAD to avoid echo-triggered false positives.
        """
        if not self._running or not self._audio_source:
            return

        # mulaw -> PCM 16-bit at 8kHz
        pcm_8k = audioop.ulaw2lin(mulaw_bytes, 2)

        # Upsample 8kHz -> 24kHz
        pcm_24k, _ = audioop.ratecv(pcm_8k, 2, 1, _PLIVO_SAMPLE_RATE, _LK_SAMPLE_RATE, None)

        # Bounded buffer: drop oldest if over limit
        self._pcm_buffer.extend(pcm_24k)
        if len(self._pcm_buffer) > _PCM_BUFFER_MAX:
            overflow = len(self._pcm_buffer) - _PCM_BUFFER_MAX
            self._pcm_buffer = self._pcm_buffer[overflow:]
            self._overflow_count += 1
            if self._overflow_count % 100 == 1:  # log every 100th overflow
                logger.warning(
                    "PCM buffer overflow #%d: dropped %d bytes (conv=%s)",
                    self._overflow_count, overflow, self.conversation_id,
                )

        # Emit complete frames
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
    # Participant audio OUT: LiveKit room -> Plivo (THE CRITICAL PATH)
    # ------------------------------------------------------------------

    async def _forward_participant_audio(
        self, audio_stream: rtc.AudioStream, identity: str
    ) -> None:
        """Forward a participant's audio track from LiveKit to Plivo via playAudio.

        This is the ONLY path for participant audio to reach the caller.
        Plivo's bidirectional stream only delivers caller audio TO us;
        we must send participant audio BACK via playAudio events.

        Audio arrives as PCM 16-bit 24kHz. We downsample to 8kHz using
        audioop.ratecv with persistent state across frames to avoid
        frame-boundary discontinuities, then encode to mulaw for Plivo.
        """
        chunks_sent = 0
        frames_received = 0
        empty_frames = 0
        local_mulaw_buf = bytearray()
        _consecutive_send_failures = 0
        _MAX_SEND_FAILURES = 3  # kill bridge after 3 consecutive failures
        _ratecv_state = None  # persistent resampler state across frames

        logger.info(
            "Audio forwarding started for %s: conv=%s, stream_sid=%s",
            identity, self.conversation_id, self._stream_sid,
        )

        try:
            async for event in audio_stream:
                if not self._running:
                    break

                # Skip forwarding when on hold
                if self._hold_active:
                    continue

                frame: rtc.AudioFrame = event.frame
                pcm_data = bytes(frame.data)
                frames_received += 1

                # Log first few frames for debugging
                if frames_received <= 5:
                    rms = audioop.rms(pcm_data, 2) if pcm_data else 0
                    logger.info(
                        "[%s] Audio frame #%d: %d bytes, rms=%d, sr=%d, ch=%d, samples=%d",
                        identity, frames_received, len(pcm_data), rms,
                        frame.sample_rate, frame.num_channels, frame.samples_per_channel,
                    )
                elif frames_received == 6:
                    logger.info("[%s] Suppressing per-frame logs after frame 5", identity)

                if not pcm_data:
                    empty_frames += 1
                    continue

                # Downsample PCM 16-bit 24kHz -> 8kHz with stateful resampler,
                # then encode to mulaw for Plivo.
                try:
                    pcm_8k, _ratecv_state = audioop.ratecv(
                        pcm_data, 2, 1, _LK_SAMPLE_RATE, _PLIVO_SAMPLE_RATE, _ratecv_state
                    )
                    mulaw_data = audioop.lin2ulaw(pcm_8k, 2)
                except audioop.error as e:
                    if frames_received <= 5:
                        logger.warning("[%s] audio conversion failed on frame #%d: %s", identity, frames_received, e)
                    continue

                local_mulaw_buf.extend(mulaw_data)

                # Send buffered chunks to Plivo
                while len(local_mulaw_buf) >= _PLIVO_CHUNK_SIZE:
                    chunk = bytes(local_mulaw_buf[:_PLIVO_CHUNK_SIZE])
                    local_mulaw_buf = local_mulaw_buf[_PLIVO_CHUNK_SIZE:]

                    # Bounded buffer: drop oldest if backed up
                    if len(local_mulaw_buf) > _MULAW_BUFFER_MAX:
                        overflow = len(local_mulaw_buf) - _MULAW_BUFFER_MAX
                        local_mulaw_buf = local_mulaw_buf[overflow:]

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
                        _consecutive_send_failures = 0  # reset on success
                        if chunks_sent == 1:
                            logger.info(
                                "[%s] First audio chunk sent to Plivo (%d bytes, after %d frames)",
                                identity, _PLIVO_CHUNK_SIZE, frames_received,
                            )
                    except Exception:
                        _consecutive_send_failures += 1
                        logger.warning(
                            "[%s] Failed to send audio to Plivo (chunk #%d, failure %d/%d)",
                            identity, chunks_sent, _consecutive_send_failures, _MAX_SEND_FAILURES,
                        )
                        if _consecutive_send_failures >= _MAX_SEND_FAILURES:
                            logger.error(
                                "[%s] Too many consecutive send failures — stopping bridge",
                                identity,
                            )
                            self._running = False
                            return
                        await asyncio.sleep(0.05)  # 50ms backoff
                        continue

            # Flush remaining buffer
            if local_mulaw_buf and self._running:
                try:
                    await self._plivo_send({
                        "event": "playAudio",
                        "streamId": self._stream_sid,
                        "media": {
                            "contentType": "audio/x-mulaw",
                            "sampleRate": 8000,
                            "payload": base64.b64encode(bytes(local_mulaw_buf)).decode("ascii"),
                        },
                    })
                    chunks_sent += 1
                except Exception:
                    pass

        except asyncio.CancelledError:
            pass
        except (ConnectionError, OSError) as exc:
            logger.warning("[%s] Audio forwarding lost connection: %s", identity, exc)
        except Exception:
            logger.exception("[%s] Unexpected error forwarding audio to Plivo", identity)
        finally:
            logger.info(
                "[%s] Audio forwarding ended: %d chunks sent, %d frames received, %d empty (conv=%s)",
                identity, chunks_sent, frames_received, empty_frames, self.conversation_id,
            )

    # ------------------------------------------------------------------
    # Interruption support: clear agent audio when caller speaks
    # ------------------------------------------------------------------

    async def clear_agent_audio(self) -> None:
        """Send clearAudio to Plivo to stop any queued agent audio.

        Called when:
          - Agent data channel signal {"type": "barge_in"} (adaptive interruption)
          - Handoff or supervisor barge
        """
        if not self._stream_sid or not self._running:
            return
        try:
            await self._plivo_send({
                "event": "clearAudio",
                "streamId": self._stream_sid,
            })
            logger.info("Cleared Plivo audio (barge-in): conv=%s", self.conversation_id)
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
        self._disconnected.set()
        # Cancel all participant forwarding tasks
        for identity, task in self._subscribe_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._subscribe_tasks.clear()
        if self._room:
            await self._room.disconnect()
            self._room = None
        self._audio_source = None
        self._pcm_buffer.clear()
        logger.info("PlivoLiveKitBridge stopped: room=%s", self.room_name)
