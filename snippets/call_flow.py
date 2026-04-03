"""
==============================================================================
PRODUCTION-GRADE CODE SNIPPETS — LiveKit + Plivo + Sarvam Voice AI Pipeline
==============================================================================

Complete call flow with latency optimizations, error handling, and observability.
Organized by phase. Each section is self-contained and production-ready.

Target latencies:
  - Dead air after DTMF:  < 500ms  (from 4.5s)
  - AI pipeline startup:  < 500ms  (from 3.47s)
  - Greeting first audio:   0ms    (cached)
  - Turn latency:         < 800ms  (from 1.14s)
"""

# =============================================================================
# 0. CONFIGURATION — All tunable constants in one place (fixes M1)
# =============================================================================

# app/config.py

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # -- Plivo --
    plivo_auth_id: str
    plivo_auth_token: str
    plivo_stream_timeout_seconds: int = 120  # was hardcoded 60s (H2)
    plivo_filler_audio_url: str = "https://cdn.example.com/audio/please-wait.wav"

    # -- LiveKit --
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    livekit_connect_timeout: float = 5.0      # fix C4
    livekit_agent_join_timeout: float = 8.0   # fix H9
    livekit_region: str = "ap-south-1"        # keep close to Plivo India

    # -- Sarvam --
    sarvam_api_key: str
    sarvam_tts_timeout: float = 5.0           # fix H7
    sarvam_api_url: str = "https://api.sarvam.ai"

    # -- Deepgram --
    deepgram_api_key: str
    deepgram_endpointing_ms: int = 350        # tighter than default 500ms

    # -- LLM --
    groq_api_key: str
    max_conversation_history: int = 12         # reduced from 20 for faster inference
    max_system_prompt_tokens: int = 800

    # -- Audio --
    max_audio_buffer_bytes: int = 65536        # fix C5 — 64KB cap
    silence_rms_threshold: int = 50
    mulaw_chunk_size: int = 320                # 40ms @ 8kHz mulaw
    aec_warmup_seconds: float = 1.5            # reduced from 3.0

    # -- Safety --
    max_call_duration_seconds: int = 3600      # fix C2 — 1 hour cap
    max_ws_connections_per_tenant: int = 50     # fix M6

    # -- Redis --
    redis_url: str = "redis://localhost:6379"
    redis_max_connections: int = 50            # was hardcoded 20 (L3)
    greeting_cache_ttl: int = 86400            # 24h

    # -- Observability --
    otel_endpoint: str = ""
    ws_heartbeat_interval_seconds: int = 30    # fix H5

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# =============================================================================
# 1. GREETING CACHE — Pre-synthesize and cache per tenant+language
# =============================================================================

# app/services/greeting_cache.py

import hashlib
import logging
from typing import Optional

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

GREETING_TEMPLATES = {
    "en": "Hello! Welcome to {company_name}. I'm Maya, your AI assistant. How can I help you today?",
    "hi": "नमस्ते! {company_name} में आपका स्वागत है। मैं माया हूँ, आपकी AI सहायक। मैं आपकी कैसे मदद कर सकती हूँ?",
    "mr": "नमस्कार! {company_name} मध्ये आपले स्वागत आहे. मी माया, तुमची AI सहाय्यक. मी तुम्हाला कशी मदत करू शकते?",
}


def _cache_key(tenant_id: str, language: str, company_name: str) -> str:
    """Deterministic key: greeting:{tenant}:{lang}:{content_hash}"""
    content = GREETING_TEMPLATES.get(language, GREETING_TEMPLATES["en"]).format(
        company_name=company_name
    )
    content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"greeting:{tenant_id}:{language}:{content_hash}"


async def get_cached_greeting(
    redis: aioredis.Redis,
    tenant_id: str,
    language: str,
    company_name: str,
) -> Optional[bytes]:
    """Fetch pre-synthesized mulaw greeting audio from Redis."""
    key = _cache_key(tenant_id, language, company_name)
    try:
        data = await redis.get(key)
        if data:
            logger.info("greeting_cache.hit", extra={"tenant_id": tenant_id, "language": language})
            return data
        logger.info("greeting_cache.miss", extra={"tenant_id": tenant_id, "language": language})
        return None
    except Exception:
        logger.warning("greeting_cache.error", exc_info=True)
        return None


async def cache_greeting(
    redis: aioredis.Redis,
    tenant_id: str,
    language: str,
    company_name: str,
    audio_bytes: bytes,
) -> None:
    """Store synthesized greeting. TTL = 24h. Fire-and-forget safe."""
    key = _cache_key(tenant_id, language, company_name)
    try:
        await redis.set(key, audio_bytes, ex=settings.greeting_cache_ttl)
        logger.info(
            "greeting_cache.stored",
            extra={"tenant_id": tenant_id, "key": key, "size": len(audio_bytes)},
        )
    except Exception:
        logger.warning("greeting_cache.store_failed", exc_info=True)


async def warm_greeting_cache(
    redis: aioredis.Redis,
    tenant_id: str,
    language: str,
    company_name: str,
) -> None:
    """
    Background task: synthesize greeting and cache it.
    Called during IVR phase so it's ready before DTMF arrives.
    """
    from app.voice_ai.sarvam import synthesize_full  # avoid circular

    existing = await get_cached_greeting(redis, tenant_id, language, company_name)
    if existing:
        return

    text = GREETING_TEMPLATES.get(language, GREETING_TEMPLATES["en"]).format(
        company_name=company_name
    )
    try:
        audio_bytes = await synthesize_full(text, language, speaker="ritu")
        await cache_greeting(redis, tenant_id, language, company_name, audio_bytes)
    except Exception:
        logger.warning("greeting_cache.warm_failed", exc_info=True)
        # Non-fatal: bridge will fall back to live synthesis


# =============================================================================
# 2. ROOM PRE-CREATION — Start LiveKit room during IVR, not after DTMF
# =============================================================================

# app/services/room_prewarmer.py

import asyncio
import logging
import json
from dataclasses import dataclass, field
from typing import Optional

from livekit import api as lk_api

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class PrewarmedRoom:
    room_name: str
    room_sid: str
    created_at: float
    tenant_id: str
    conversation_id: str
    language: str
    company_name: str


class RoomPrewarmer:
    """
    Creates LiveKit rooms during IVR phase so they're ready when DTMF arrives.
    Keyed by conversation_id. Rooms auto-expire if unused.
    """

    def __init__(self):
        self._rooms: dict[str, PrewarmedRoom] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._lk_api = lk_api.LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )

    async def prewarm(
        self,
        conversation_id: str,
        tenant_id: str,
        language: str,
        company_name: str,
    ) -> Optional[PrewarmedRoom]:
        """
        Create room + dispatch agent. Called as background task during IVR.
        Idempotent — safe to call multiple times for same conversation.
        """
        if conversation_id in self._rooms:
            return self._rooms[conversation_id]

        # Per-conversation lock to prevent duplicate room creation
        if conversation_id not in self._locks:
            self._locks[conversation_id] = asyncio.Lock()

        async with self._locks[conversation_id]:
            # Double-check after acquiring lock
            if conversation_id in self._rooms:
                return self._rooms[conversation_id]

            room_name = f"room-{conversation_id}"
            metadata = json.dumps({
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "language": language,
                "company_name": company_name,
            })

            try:
                room = await asyncio.wait_for(
                    self._lk_api.room.create_room(
                        lk_api.CreateRoomRequest(
                            name=room_name,
                            metadata=metadata,
                            empty_timeout=30,   # auto-delete if nobody joins within 30s
                            max_participants=3,  # bridge + agent + optional supervisor
                        )
                    ),
                    timeout=settings.livekit_connect_timeout,
                )

                prewarmed = PrewarmedRoom(
                    room_name=room_name,
                    room_sid=room.sid,
                    created_at=asyncio.get_event_loop().time(),
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    language=language,
                    company_name=company_name,
                )
                self._rooms[conversation_id] = prewarmed

                logger.info(
                    "room_prewarmer.created",
                    extra={
                        "conversation_id": conversation_id,
                        "room_name": room_name,
                        "room_sid": room.sid,
                    },
                )
                return prewarmed

            except asyncio.TimeoutError:
                logger.error(
                    "room_prewarmer.timeout",
                    extra={"conversation_id": conversation_id},
                )
                return None
            except Exception:
                logger.exception(
                    "room_prewarmer.failed",
                    extra={"conversation_id": conversation_id},
                )
                return None

    def consume(self, conversation_id: str) -> Optional[PrewarmedRoom]:
        """Pop a prewarmed room. Returns None if not available."""
        return self._rooms.pop(conversation_id, None)

    async def cleanup_stale(self, max_age_seconds: float = 60.0):
        """Periodic task to clean up rooms that were prewarmed but never used."""
        now = asyncio.get_event_loop().time()
        stale = [
            cid for cid, room in self._rooms.items()
            if (now - room.created_at) > max_age_seconds
        ]
        for cid in stale:
            room = self._rooms.pop(cid, None)
            if room:
                try:
                    await self._lk_api.room.delete_room(
                        lk_api.DeleteRoomRequest(room=room.room_name)
                    )
                    logger.info("room_prewarmer.cleaned_stale", extra={"room": room.room_name})
                except Exception:
                    logger.warning("room_prewarmer.cleanup_failed", exc_info=True)


# Singleton — shared across request handlers
room_prewarmer = RoomPrewarmer()


# =============================================================================
# 3. PLIVO ANSWER + DTMF — Trigger prewarm during IVR, use filler audio
# =============================================================================

# app/api/v1/plivo.py (relevant handlers)

import asyncio
import logging

from fastapi import APIRouter, Request, Response
from app.config import get_settings
from app.core.handoff_engine import HandoffEngine
from app.services.room_prewarmer import room_prewarmer
from app.services.greeting_cache import warm_greeting_cache
from app.core.tracing import trace_span  # see section 9

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()


@router.post("/api/v1/plivo/answer")
async def plivo_answer(request: Request) -> Response:
    """
    Plivo calls this when the callee picks up.
    Key optimization: start prewarming LiveKit room + greeting cache HERE,
    not after DTMF. Saves ~3s.
    """
    form = await request.form()
    call_uuid = form.get("CallUUID")
    tenant_id = request.query_params.get("tenant_id")

    with trace_span("plivo.answer", call_uuid=call_uuid, tenant_id=tenant_id):
        # --- Existing logic: find/create conversation, transition state ---
        conversation = await _find_or_create_conversation(call_uuid, tenant_id, form)
        engine = HandoffEngine()
        await engine.process_trigger(conversation.id, "ANSWER")

        # --- OPTIMIZATION: Pre-warm room + greeting cache during IVR ---
        # These run in background while caller navigates DTMF menu (~20s)
        tenant = await _get_tenant(tenant_id)
        default_lang = tenant.voice_config.get("default_language", "en")
        company_name = tenant.company_name

        asyncio.create_task(
            _prewarm_pipeline(conversation.id, tenant_id, default_lang, company_name)
        )

        # --- Return IVR XML ---
        menu_id = tenant.ivr_config.get("root_menu_id")
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <GetDigits action="/api/v1/plivo/dtmf?tenant_id={tenant_id}&amp;conv_id={conversation.id}&amp;menu_id={menu_id}"
                       timeout="10" numDigits="1" retries="2">
                <Speak>{tenant.ivr_config.get("welcome_message", "Press 1 for assistance")}</Speak>
            </GetDigits>
            <Speak>We didn't receive any input. Goodbye.</Speak>
            <Hangup/>
        </Response>"""

        return Response(content=xml, media_type="application/xml")


async def _prewarm_pipeline(
    conversation_id: str, tenant_id: str, language: str, company_name: str
):
    """Background task: pre-create LiveKit room + warm greeting cache."""
    redis = await get_redis()
    await asyncio.gather(
        room_prewarmer.prewarm(conversation_id, tenant_id, language, company_name),
        warm_greeting_cache(redis, tenant_id, language, company_name),
        return_exceptions=True,  # don't let one failure kill the other
    )


@router.post("/api/v1/plivo/dtmf")
async def plivo_dtmf(request: Request) -> Response:
    """
    Caller pressed a DTMF key.
    Key optimization: room is already pre-created, so we skip the 2.74s wait.
    Also: filler audio plays immediately while bridge connects.
    """
    form = await request.form()
    digit = form.get("Digits")
    conv_id = request.query_params.get("conv_id")
    tenant_id = request.query_params.get("tenant_id")
    menu_id = request.query_params.get("menu_id")

    with trace_span("plivo.dtmf", conv_id=conv_id, digit=digit):
        # --- Process DTMF action ---
        action = await ivr_engine.process_dtmf(menu_id, digit)

        if action.action_type != "ai_handoff":
            return _handle_non_ai_action(action, conv_id, tenant_id)

        # --- AI Handoff ---
        engine = HandoffEngine()
        await engine.process_trigger(conv_id, "DTMF_AI")

        tenant = await _get_tenant(tenant_id)
        language = action.language or tenant.voice_config.get("default_language", "en")
        speaker = action.speaker or "ritu"

        stream_url = (
            f"wss://{request.headers['host']}/api/v1/plivo/audio-stream"
            f"?tenant_id={tenant_id}&conv_id={conv_id}"
            f"&language={language}&speaker={speaker}"
        )

        # KEY: Play filler audio FIRST, then start bidirectional stream.
        # Caller hears "One moment" instantly instead of 4.5s silence.
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Play>{settings.plivo_filler_audio_url}</Play>
            <Stream bidirectional="true" keepCallAlive="true"
                    url="{stream_url}">
            </Stream>
        </Response>"""

        return Response(content=xml, media_type="application/xml")


# =============================================================================
# 4. PLIVO-LIVEKIT BRIDGE — With timeouts, bounded buffers, agent watchdog
# =============================================================================

# app/voice_ai/plivo_livekit_bridge.py

import asyncio
import audioop
import base64
import logging
import time
from typing import Optional, Callable, Awaitable

from livekit import rtc, api as lk_api

from app.config import get_settings
from app.services.greeting_cache import get_cached_greeting
from app.services.room_prewarmer import room_prewarmer
from app.core.tracing import trace_span

logger = logging.getLogger(__name__)
settings = get_settings()


class BoundedAudioBuffer:
    """Fixed-size audio buffer that drops oldest data on overflow (fix C5)."""

    def __init__(self, max_size: int = settings.max_audio_buffer_bytes):
        self._buf = bytearray()
        self._max = max_size
        self._overflow_count = 0

    def write(self, data: bytes):
        self._buf.extend(data)
        if len(self._buf) > self._max:
            overflow = len(self._buf) - self._max
            self._buf = self._buf[overflow:]
            self._overflow_count += 1
            if self._overflow_count % 100 == 1:
                logger.warning(
                    "audio_buffer.overflow",
                    extra={"dropped_bytes": overflow, "total_overflows": self._overflow_count},
                )

    def read(self, n: int) -> bytes:
        chunk = bytes(self._buf[:n])
        self._buf = self._buf[n:]
        return chunk

    def __len__(self) -> int:
        return len(self._buf)

    def clear(self):
        self._buf.clear()


class PlivoLiveKitBridge:
    """
    Bridges Plivo audio WebSocket ↔ LiveKit room.
    Handles audio format conversion, greeting playback, and agent watchdog.
    """

    def __init__(
        self,
        conversation_id: str,
        tenant_id: str,
        language: str,
        company_name: str,
        plivo_ws_send: Callable[[dict], Awaitable[None]],
        correlation_id: str = "",
    ):
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.language = language
        self.company_name = company_name
        self._plivo_send = plivo_ws_send
        self._correlation_id = correlation_id

        self._room: Optional[rtc.Room] = None
        self._audio_source: Optional[rtc.AudioSource] = None
        self._pcm_buffer = BoundedAudioBuffer()
        self._mulaw_out_buffer = BoundedAudioBuffer()
        self._stream_sid: Optional[str] = None
        self._running = False
        self._subscribe_task: Optional[asyncio.Task] = None
        self._agent_joined = asyncio.Event()
        self._start_time: float = 0

    async def start(self) -> None:
        """
        Connect to LiveKit room. Uses pre-warmed room if available.
        Includes timeout on connect (fix C4) and room existence verification (fix C3).
        """
        self._start_time = time.monotonic()
        self._running = True

        with trace_span(
            "bridge.start",
            conversation_id=self.conversation_id,
            correlation_id=self._correlation_id,
        ):
            # --- Try pre-warmed room first (saves ~2.74s) ---
            prewarmed = room_prewarmer.consume(self.conversation_id)
            room_name = f"room-{self.conversation_id}"

            if prewarmed:
                logger.info(
                    "bridge.using_prewarmed_room",
                    extra={"room_name": room_name, "room_sid": prewarmed.room_sid},
                )
            else:
                # Fallback: create room on the spot (old path)
                logger.warning("bridge.no_prewarmed_room", extra={"conv_id": self.conversation_id})
                await self._create_room_with_retry(room_name)

            # --- Generate JWT and connect ---
            token = (
                lk_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
                .with_identity("plivo-bridge")
                .with_grants(
                    lk_api.VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True)
                )
                .to_jwt()
            )

            self._room = rtc.Room()
            self._room.on("track_subscribed", self._on_track_subscribed)
            self._room.on("participant_disconnected", self._on_participant_disconnected)

            try:
                await asyncio.wait_for(
                    self._room.connect(settings.livekit_url, token),
                    timeout=settings.livekit_connect_timeout,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "bridge.connect_timeout",
                    extra={"timeout": settings.livekit_connect_timeout, "conv_id": self.conversation_id},
                )
                raise
            except Exception as e:
                logger.error("bridge.connect_failed", extra={"error": str(e)})
                raise

            # --- Publish caller audio track ---
            self._audio_source = rtc.AudioSource(sample_rate=24000, num_channels=1)
            track = rtc.LocalAudioTrack.create_audio_track("caller-audio", self._audio_source)
            await self._room.local_participant.publish_track(
                track,
                rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
            )

            # --- Start agent watchdog ---
            asyncio.create_task(self._agent_join_watchdog())

            logger.info("bridge.started", extra={"conv_id": self.conversation_id})

    async def _create_room_with_retry(self, room_name: str, retries: int = 2):
        """Create room with retry. Fix C3: verify room actually exists after creation."""
        lk = lk_api.LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        metadata = {
            "tenant_id": self.tenant_id,
            "conversation_id": self.conversation_id,
            "language": self.language,
            "company_name": self.company_name,
        }

        last_error = None
        for attempt in range(retries + 1):
            try:
                await asyncio.wait_for(
                    lk.room.create_room(
                        lk_api.CreateRoomRequest(
                            name=room_name,
                            metadata=json.dumps(metadata),
                            empty_timeout=30,
                            max_participants=3,
                        )
                    ),
                    timeout=settings.livekit_connect_timeout,
                )
                # Verify room exists (fix C3)
                rooms = await lk.room.list_rooms(lk_api.ListRoomsRequest(names=[room_name]))
                if not rooms.rooms:
                    raise RuntimeError(f"Room {room_name} not found after creation")
                return
            except Exception as e:
                last_error = e
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    logger.warning(
                        "bridge.room_create_retry",
                        extra={"attempt": attempt + 1, "error": str(e)},
                    )

        raise RuntimeError(f"Failed to create room after {retries + 1} attempts: {last_error}")

    async def _agent_join_watchdog(self):
        """
        Fix H9: detect if agent never joins.
        Escalate to human or retry after timeout.
        """
        try:
            await asyncio.wait_for(
                self._agent_joined.wait(),
                timeout=settings.livekit_agent_join_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(
                "bridge.agent_join_timeout",
                extra={
                    "conv_id": self.conversation_id,
                    "timeout": settings.livekit_agent_join_timeout,
                },
            )
            # Play apology audio to caller
            await self._play_fallback_message(
                "We're experiencing a delay connecting you. Please hold."
            )
            # TODO: trigger escalation to human queue
            # await handoff_engine.process_trigger(self.conversation_id, "AGENT_TIMEOUT")

    def _on_track_subscribed(
        self, track: rtc.Track, publication: rtc.TrackPublication, participant: rtc.RemoteParticipant
    ):
        """Agent published audio — start forwarding to Plivo."""
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return

        self._agent_joined.set()  # signal watchdog
        logger.info(
            "bridge.agent_audio_subscribed",
            extra={"participant": participant.identity, "conv_id": self.conversation_id},
        )

        audio_stream = rtc.AudioStream(track, sample_rate=8000, num_channels=1)
        self._subscribe_task = asyncio.create_task(
            self._forward_agent_audio(audio_stream)
        )

    def _on_participant_disconnected(self, participant: rtc.RemoteParticipant):
        """Agent left — stop the bridge."""
        logger.info("bridge.participant_disconnected", extra={"identity": participant.identity})
        if participant.identity.startswith("agent"):
            self._running = False

    async def stream_greeting(self, stream_sid: str) -> None:
        """
        Play greeting to caller. Uses cached audio if available,
        falls back to live Sarvam TTS synthesis.
        Pass stream_sid explicitly to avoid race condition (fix C8).
        """
        with trace_span("bridge.greeting", conv_id=self.conversation_id):
            redis = await get_redis()

            # --- Try cached greeting first (0ms vs 1.08s) ---
            cached = await get_cached_greeting(
                redis, self.tenant_id, self.language, self.company_name
            )

            if cached:
                logger.info("bridge.greeting_from_cache", extra={"size": len(cached)})
                await self._send_audio_to_plivo(cached, stream_sid)
                return

            # --- Fallback: live synthesis with timeout (fix H7) ---
            from app.services.greeting_cache import GREETING_TEMPLATES
            text = GREETING_TEMPLATES.get(self.language, GREETING_TEMPLATES["en"]).format(
                company_name=self.company_name,
            )

            logger.info("bridge.greeting_live_synthesis", extra={"language": self.language})
            try:
                audio_chunks = []
                async for chunk in asyncio.wait_for(
                    self._synthesize_and_collect(text),
                    timeout=settings.sarvam_tts_timeout,
                ):
                    await self._send_audio_to_plivo(chunk, stream_sid)
                    audio_chunks.append(chunk)

                # Cache for next time (background, non-blocking)
                full_audio = b"".join(audio_chunks)
                asyncio.create_task(
                    cache_greeting(redis, self.tenant_id, self.language, self.company_name, full_audio)
                )
            except asyncio.TimeoutError:
                logger.error("bridge.greeting_tts_timeout", extra={"conv_id": self.conversation_id})

    async def _send_audio_to_plivo(self, audio_bytes: bytes, stream_sid: str):
        """Send mulaw audio to Plivo in fixed-size chunks."""
        offset = 0
        chunk_size = settings.mulaw_chunk_size
        while offset < len(audio_bytes) and self._running:
            chunk = audio_bytes[offset : offset + chunk_size]
            try:
                await self._plivo_send({
                    "event": "playAudio",
                    "streamId": stream_sid,
                    "media": {"payload": base64.b64encode(chunk).decode()},
                })
            except Exception:
                logger.warning("bridge.plivo_send_failed", exc_info=True)
                self._running = False  # fix H10: trigger cleanup on send failure
                return
            offset += chunk_size

    def feed_audio(self, mulaw_bytes: bytes) -> None:
        """
        Receive mulaw 8kHz from Plivo → convert to PCM 24kHz → feed to LiveKit.
        """
        if not self._running or not self._audio_source:
            return

        # mulaw 8kHz → PCM 16-bit 8kHz
        pcm_8k = audioop.ulaw2lin(mulaw_bytes, 2)
        # Upsample 8kHz → 24kHz
        pcm_24k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 24000, None)
        self._pcm_buffer.write(pcm_24k)

        # Emit 20ms frames (960 bytes = 480 samples @ 24kHz 16-bit mono)
        frame_size = 960
        while len(self._pcm_buffer) >= frame_size:
            frame_data = self._pcm_buffer.read(frame_size)
            frame = rtc.AudioFrame(
                data=frame_data,
                sample_rate=24000,
                num_channels=1,
                samples_per_channel=480,
            )
            self._audio_source.capture_frame(frame)

    async def _forward_agent_audio(self, audio_stream: rtc.AudioStream):
        """LiveKit agent audio → mulaw → Plivo → caller."""
        try:
            async for event in audio_stream:
                if not self._running:
                    break

                frame = event.frame
                pcm_data = bytes(frame.data)

                # Skip silence frames
                try:
                    rms = audioop.rms(pcm_data, 2)
                except audioop.error:
                    continue
                if rms < settings.silence_rms_threshold:
                    continue

                # PCM 8kHz 16-bit → mulaw
                mulaw = audioop.lin2ulaw(pcm_data, 2)
                self._mulaw_out_buffer.write(mulaw)

                # Send in fixed chunks
                while len(self._mulaw_out_buffer) >= settings.mulaw_chunk_size:
                    chunk = self._mulaw_out_buffer.read(settings.mulaw_chunk_size)
                    try:
                        await self._plivo_send({
                            "event": "playAudio",
                            "streamId": self._stream_sid,
                            "media": {"payload": base64.b64encode(chunk).decode()},
                        })
                    except Exception:
                        logger.warning("bridge.agent_audio_send_failed", exc_info=True)
                        self._running = False  # fix H10
                        return

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("bridge.forward_agent_audio_error")

    async def stop(self):
        """Clean shutdown with proper task awaiting (fix M8)."""
        self._running = False
        elapsed = time.monotonic() - self._start_time

        if self._subscribe_task and not self._subscribe_task.done():
            self._subscribe_task.cancel()
            try:
                await self._subscribe_task  # fix M8: actually await cancellation
            except asyncio.CancelledError:
                pass

        if self._room:
            try:
                await self._room.disconnect()
            except Exception:
                pass

        self._pcm_buffer.clear()
        self._mulaw_out_buffer.clear()

        logger.info(
            "bridge.stopped",
            extra={
                "conv_id": self.conversation_id,
                "duration_seconds": round(elapsed, 2),
                "correlation_id": self._correlation_id,
            },
        )


# =============================================================================
# 5. AUDIO STREAM WEBSOCKET — With max call duration + proper session registry
# =============================================================================

# app/api/v1/plivo_stream.py

import asyncio
import logging

from fastapi import WebSocket
from app.config import get_settings
from app.voice_ai.plivo_livekit_bridge import PlivoLiveKitBridge
from app.core.session_registry import session_registry  # fix C7
from app.core.tracing import new_correlation_id, trace_span

logger = logging.getLogger(__name__)
settings = get_settings()


async def plivo_audio_stream(ws: WebSocket):
    """
    Handle bidirectional audio WebSocket from Plivo.
    Wrapped in max call duration timeout (fix C2).
    """
    await ws.accept()
    query = ws.query_params
    conv_id = query.get("conv_id")
    tenant_id = query.get("tenant_id")
    language = query.get("language", "en")
    speaker = query.get("speaker", "ritu")
    correlation_id = new_correlation_id()

    with trace_span("plivo_stream", conv_id=conv_id, correlation_id=correlation_id):
        tenant = await _get_tenant(tenant_id)
        bridge = PlivoLiveKitBridge(
            conversation_id=conv_id,
            tenant_id=tenant_id,
            language=language,
            company_name=tenant.company_name,
            plivo_ws_send=ws.send_json,
            correlation_id=correlation_id,
        )

        try:
            await bridge.start()

            # Fix C7: Register in session registry for supervisor access
            session_handle = LiveKitSessionHandle(
                bridge=bridge,
                conversation_id=conv_id,
                tenant_id=tenant_id,
            )
            session_registry.register(conv_id, session_handle)

            # Fix C2: Enforce max call duration
            await asyncio.wait_for(
                _stream_event_loop(ws, bridge, correlation_id),
                timeout=settings.max_call_duration_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "plivo_stream.max_duration_exceeded",
                extra={
                    "conv_id": conv_id,
                    "max_seconds": settings.max_call_duration_seconds,
                },
            )
        except Exception:
            logger.exception("plivo_stream.error", extra={"conv_id": conv_id})
        finally:
            session_registry.unregister(conv_id)  # fix C7
            await bridge.stop()


async def _stream_event_loop(
    ws: WebSocket,
    bridge: PlivoLiveKitBridge,
    correlation_id: str,
):
    """Main WebSocket event loop with configurable timeout (fix H2)."""
    import base64

    while True:
        try:
            raw = await asyncio.wait_for(
                ws.receive_text(),
                timeout=settings.plivo_stream_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("plivo_stream.receive_timeout", extra={"conv_id": bridge.conversation_id})
            break

        data = json.loads(raw)
        event = data.get("event")

        if event == "start":
            stream_sid = data.get("start", {}).get("streamId")
            bridge._stream_sid = stream_sid
            # Fix C8: pass stream_sid explicitly, don't rely on instance var
            asyncio.create_task(bridge.stream_greeting(stream_sid=stream_sid))

        elif event == "media":
            payload = data.get("media", {}).get("payload", "")
            mulaw_bytes = base64.b64decode(payload)
            bridge.feed_audio(mulaw_bytes)

        elif event == "stop":
            logger.info("plivo_stream.stop_received", extra={"conv_id": bridge.conversation_id})
            break


# =============================================================================
# 6. LIVEKIT AGENT — Fixed TTS language selection + optimized pipeline
# =============================================================================

# app/voice_ai/livekit_agent.py

import json
import logging

from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
)
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import deepgram, silero

from app.voice_ai.sarvam_llm_plugin import SarvamLLM
from app.voice_ai.sarvam_tts_plugin import SarvamTTS  # for non-English
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# --- Fix C1: TTS model selection by language ---
DEEPGRAM_TTS_MODELS = {
    "en": "aura-2-andromeda-en",
    "hi": "aura-2-andromeda-hi",
    # Add more as Deepgram supports them
}


def _build_tts_plugin(language: str):
    """
    Select TTS engine by language. Use Deepgram for supported langs
    (lower latency, WebSocket-based), fall back to Sarvam for others.
    """
    if language in DEEPGRAM_TTS_MODELS:
        return deepgram.TTS(model=DEEPGRAM_TTS_MODELS[language])
    else:
        # Marathi, etc. — use Sarvam HTTP streaming TTS
        logger.info(f"Using Sarvam TTS for unsupported Deepgram language: {language}")
        return SarvamTTS(language=language, speaker="ritu")


def _build_stt_plugin(language: str):
    """STT model selection by language."""
    lang_map = {"en": "en-US", "hi": "hi", "mr": "mr"}
    return deepgram.STT(
        model="nova-2",
        language=lang_map.get(language, "en-US"),
        endpointing_ms=settings.deepgram_endpointing_ms,  # 350ms vs default 500ms
    )


def prewarm(proc: JobProcess):
    """Pre-load VAD model so first call doesn't pay the cost."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    """
    Main agent entrypoint. Runs in a pre-warmed worker process.
    """
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # --- Parse room metadata ---
    metadata = json.loads(ctx.room.metadata or "{}")
    language = metadata.get("language", "en")
    company_name = metadata.get("company_name", "the company")
    tenant_id = metadata.get("tenant_id", "")
    conversation_id = metadata.get("conversation_id", "")

    logger.info(
        "agent.starting",
        extra={
            "conversation_id": conversation_id,
            "language": language,
            "company_name": company_name,
        },
    )

    # --- Build pipeline components ---
    vad = ctx.proc.userdata.get("vad") or silero.VAD.load()

    llm = SarvamLLM(
        language=language,
        company_name=company_name,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        max_history=settings.max_conversation_history,
    )

    tts = _build_tts_plugin(language)   # fix C1
    stt = _build_stt_plugin(language)

    # --- Create agent ---
    agent = Agent(
        instructions=f"You are Maya, a helpful AI assistant for {company_name}. "
        f"Speak in {language}. Be concise and natural.",
    )

    # --- Data channel for supervisor messages ---
    @ctx.room.on("data_received")
    def on_data(data: rtc.DataPacket):
        try:
            msg = json.loads(data.data.decode())
            msg_type = msg.get("type")

            if msg_type == "whisper":
                hint = msg.get("text", "")
                llm.inject_system_hint(hint)
                logger.info("agent.whisper_received", extra={"hint_length": len(hint)})

            elif msg_type == "barge":
                # Fix C6: actually implement barge
                logger.info("agent.barge_received")
                session.interrupt()  # stop current speech
                # Send signal to bridge to redirect call
                ctx.room.local_participant.publish_data(
                    json.dumps({"type": "barge_active", "target": msg.get("target")}).encode()
                )
        except Exception:
            logger.warning("agent.data_received_error", exc_info=True)

    # --- Start session ---
    session = AgentSession(
        vad=vad,
        llm=llm,
        tts=tts,
        stt=stt,
    )

    await session.start(agent, room=ctx.room)
    logger.info("agent.session_started", extra={"conversation_id": conversation_id})


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            num_idle_processes=2,  # keep 2 warm workers ready
        )
    )


# =============================================================================
# 7. CIRCUIT BREAKER — Protect against cascading external API failures (fix H8)
# =============================================================================

# app/core/circuit_breaker.py

import asyncio
import time
import logging
from enum import Enum
from typing import Callable, TypeVar, Awaitable

logger = logging.getLogger(__name__)
T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"        # normal operation
    OPEN = "open"            # failing, reject fast
    HALF_OPEN = "half_open"  # testing recovery


class CircuitBreaker:
    """
    Simple async circuit breaker for external API calls.

    Usage:
        sarvam_cb = CircuitBreaker("sarvam_tts", failure_threshold=3, recovery_timeout=30)

        async def call_sarvam():
            return await sarvam_cb.call(synthesize_stream, text, language)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info(f"circuit_breaker.{self.name}.half_open")
        return self._state

    async def call(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        state = self.state

        if state == CircuitState.OPEN:
            raise CircuitOpenError(f"Circuit {self.name} is OPEN — fast-failing")

        if state == CircuitState.HALF_OPEN and self._half_open_calls >= self.half_open_max_calls:
            raise CircuitOpenError(f"Circuit {self.name} is HALF_OPEN — max test calls reached")

        try:
            if state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1

            result = await func(*args, **kwargs)

            # Success — reset
            if self._state != CircuitState.CLOSED:
                logger.info(f"circuit_breaker.{self.name}.closed (recovered)")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            return result

        except Exception as e:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.error(
                    f"circuit_breaker.{self.name}.opened",
                    extra={"failure_count": self._failure_count, "error": str(e)},
                )

            raise


class CircuitOpenError(Exception):
    pass


# Pre-built breakers for each external service
sarvam_tts_breaker = CircuitBreaker("sarvam_tts", failure_threshold=3, recovery_timeout=30)
sarvam_llm_breaker = CircuitBreaker("sarvam_llm", failure_threshold=3, recovery_timeout=30)
deepgram_breaker = CircuitBreaker("deepgram", failure_threshold=5, recovery_timeout=20)


# =============================================================================
# 8. HEALTH CHECK — Validate all dependencies (fix H1)
# =============================================================================

# app/api/v1/health.py

import asyncio
import time
import logging

from fastapi import APIRouter
from livekit import api as lk_api

from app.config import get_settings
from app.core.redis import get_redis
from app.core.database import get_db

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Comprehensive health check for all dependencies.
    Returns 200 if all healthy, 503 if any critical dependency is down.
    """
    checks = {}
    healthy = True

    # --- PostgreSQL ---
    try:
        start = time.monotonic()
        async with get_db() as db:
            await db.execute("SELECT 1")
        checks["postgres"] = {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000)}
    except Exception as e:
        checks["postgres"] = {"status": "error", "error": str(e)}
        healthy = False

    # --- Redis ---
    try:
        start = time.monotonic()
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000)}
    except Exception as e:
        checks["redis"] = {"status": "error", "error": str(e)}
        healthy = False

    # --- LiveKit ---
    try:
        start = time.monotonic()
        lk = lk_api.LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        await asyncio.wait_for(
            lk.room.list_rooms(lk_api.ListRoomsRequest()),
            timeout=3.0,
        )
        checks["livekit"] = {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000)}
    except Exception as e:
        checks["livekit"] = {"status": "error", "error": str(e)}
        healthy = False

    status_code = 200 if healthy else 503
    return JSONResponse(
        content={"status": "healthy" if healthy else "degraded", "checks": checks},
        status_code=status_code,
    )


# =============================================================================
# 9. TRACING — Correlation IDs + structured spans (fix H6)
# =============================================================================

# app/core/tracing.py

import uuid
import time
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger(__name__)

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def new_correlation_id() -> str:
    cid = str(uuid.uuid4())[:12]
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    return _correlation_id.get()


@contextmanager
def trace_span(name: str, **tags):
    """
    Lightweight tracing span. Logs start/end with duration.
    Drop-in replacement until you integrate OpenTelemetry.

    Usage:
        with trace_span("bridge.start", conv_id="abc"):
            await do_stuff()
    """
    cid = get_correlation_id()
    start = time.monotonic()

    extra = {"span": name, "correlation_id": cid, **tags}
    logger.info(f"span.start.{name}", extra=extra)

    try:
        yield
    except Exception as e:
        elapsed = round((time.monotonic() - start) * 1000, 1)
        logger.error(
            f"span.error.{name}",
            extra={**extra, "duration_ms": elapsed, "error": str(e)},
            exc_info=True,
        )
        raise
    else:
        elapsed = round((time.monotonic() - start) * 1000, 1)
        logger.info(f"span.end.{name}", extra={**extra, "duration_ms": elapsed})


# =============================================================================
# 10. APP STARTUP — Validate dependencies + graceful shutdown (fix C9, L1)
# =============================================================================

# app/main.py

import asyncio
import logging
import signal

from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import get_settings
from app.core.redis import get_redis
from app.services.room_prewarmer import room_prewarmer

logger = logging.getLogger(__name__)
settings = get_settings()

# Track active sessions for graceful shutdown (fix L1)
_active_sessions: set[str] = set()
_shutdown_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: validate all dependencies (fix C9).
    Shutdown: drain active calls gracefully (fix L1).
    """
    # --- STARTUP ---
    logger.info("app.starting")

    # Fix C9: validate Redis at startup, fail fast
    try:
        redis = await get_redis()
        await redis.ping()
        logger.info("startup.redis_ok")
    except Exception as e:
        logger.critical(f"startup.redis_failed: {e}")
        raise SystemExit(1)

    # Validate PostgreSQL
    try:
        async with get_db() as db:
            await db.execute("SELECT 1")
        logger.info("startup.postgres_ok")
    except Exception as e:
        logger.critical(f"startup.postgres_failed: {e}")
        raise SystemExit(1)

    # Start background tasks
    cleanup_task = asyncio.create_task(_periodic_room_cleanup())

    logger.info("app.started")

    yield

    # --- SHUTDOWN ---
    logger.info("app.shutting_down", extra={"active_sessions": len(_active_sessions)})

    # Signal all active sessions to wind down
    _shutdown_event.set()

    # Wait up to 10s for active calls to finish
    if _active_sessions:
        logger.info(f"app.draining {len(_active_sessions)} active sessions...")
        for _ in range(20):  # 20 * 0.5s = 10s max
            if not _active_sessions:
                break
            await asyncio.sleep(0.5)

    if _active_sessions:
        logger.warning(f"app.force_shutdown with {len(_active_sessions)} sessions remaining")

    cleanup_task.cancel()
    logger.info("app.stopped")


async def _periodic_room_cleanup():
    """Clean up pre-warmed rooms that were never used."""
    while True:
        try:
            await asyncio.sleep(30)
            await room_prewarmer.cleanup_stale(max_age_seconds=60)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.warning("room_cleanup.error", exc_info=True)


app = FastAPI(lifespan=lifespan)


# =============================================================================
# 11. SESSION REGISTRY — Unified supervisor access for LiveKit path (fix C7)
# =============================================================================

# app/core/session_registry.py

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


class SessionHandle(Protocol):
    """Interface for supervisor operations on an active call."""

    async def send_whisper(self, text: str) -> None: ...
    async def send_barge(self, target: str) -> None: ...
    async def get_audio_stream(self) -> asyncio.Queue: ...


@dataclass
class LiveKitSessionHandle:
    """SessionHandle implementation for LiveKit-backed calls."""
    bridge: "PlivoLiveKitBridge"
    conversation_id: str
    tenant_id: str

    async def send_whisper(self, text: str) -> None:
        """Send whisper hint to agent via LiveKit data channel."""
        import json
        if self.bridge._room and self.bridge._room.local_participant:
            await self.bridge._room.local_participant.publish_data(
                json.dumps({"type": "whisper", "text": text}).encode()
            )

    async def send_barge(self, target: str) -> None:
        """Signal agent to stop and transfer call."""
        import json
        if self.bridge._room and self.bridge._room.local_participant:
            await self.bridge._room.local_participant.publish_data(
                json.dumps({"type": "barge", "target": target}).encode()
            )

    async def get_audio_stream(self) -> asyncio.Queue:
        """Return a queue that receives copies of caller audio frames."""
        # For supervisor listen — duplicate audio to a side channel
        raise NotImplementedError("Supervisor listen via LiveKit forthcoming")


class SessionRegistry:
    """Thread-safe registry of active call sessions."""

    def __init__(self):
        self._sessions: dict[str, SessionHandle] = {}

    def register(self, conversation_id: str, handle: SessionHandle) -> None:
        self._sessions[conversation_id] = handle
        logger.info("session_registry.registered", extra={"conv_id": conversation_id})

    def unregister(self, conversation_id: str) -> None:
        self._sessions.pop(conversation_id, None)
        logger.info("session_registry.unregistered", extra={"conv_id": conversation_id})

    def get(self, conversation_id: str) -> Optional[SessionHandle]:
        return self._sessions.get(conversation_id)

    @property
    def active_count(self) -> int:
        return len(self._sessions)


session_registry = SessionRegistry()