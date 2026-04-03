"""Plivo-to-LiveKit audio bridge.

Receives mulaw audio from a Plivo bidirectional WebSocket stream,
converts to PCM, and publishes it as an audio track in a LiveKit room.
Subscribes to the LiveKit Agent's audio track and sends PCM->mulaw
back to Plivo.

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
# Also suppress lk.transcription noise
logging.getLogger().addFilter(type("_F", (logging.Filter,), {
    "filter": staticmethod(lambda r: "lk.transcription" not in r.getMessage())
})())

logger = logging.getLogger(__name__)

# LiveKit expects specific frame sizes; 20ms at 24kHz mono 16-bit = 960 samples = 1920 bytes
_LK_SAMPLE_RATE = 24000
_LK_FRAME_DURATION_MS = 20
_LK_SAMPLES_PER_FRAME = _LK_SAMPLE_RATE * _LK_FRAME_DURATION_MS // 1000  # 480
_LK_FRAME_BYTES = _LK_SAMPLES_PER_FRAME * 2  # 960 bytes (16-bit mono)

# Plivo sends 20ms at 8kHz mulaw = 160 bytes
_PLIVO_SAMPLE_RATE = 8000


class PlivoLiveKitBridge:
    """Bridges audio between a Plivo WebSocket and a LiveKit room.

    Lifecycle:
        bridge = PlivoLiveKitBridge(...)
        await bridge.start()        # Creates room, joins as participant
        await bridge.feed_audio(mulaw_bytes)  # Called for each Plivo media chunk
        await bridge.stop()          # Leaves room, cleans up
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
        self._mulaw_out_buffer = bytearray()  # Buffer outgoing mulaw for Plivo
        self._running = False
        self._subscribe_task: asyncio.Task | None = None

    @property
    def room_name(self) -> str:
        return f"room-{self.conversation_id}"

    async def start(self) -> None:
        """Create a LiveKit room, join as plivo-bridge, and start listening."""
        # 1. Create room via LiveKit API
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
        except Exception:
            # Room may already exist (idempotent)
            logger.debug("Room %s may already exist, continuing", self.room_name)
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

        # Subscribe to agent audio tracks
        @self._room.on("track_subscribed")
        def _on_track(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity != "plivo-bridge":
                logger.info("Subscribed to agent audio track from %s", participant.identity)
                # Request audio at 8kHz mono to match Plivo — avoids extra resampling
                audio_stream = rtc.AudioStream(
                    track, sample_rate=_PLIVO_SAMPLE_RATE, num_channels=1
                )
                self._subscribe_task = asyncio.create_task(
                    self._forward_agent_audio(audio_stream)
                )

        await self._room.connect(settings.livekit_url, jwt_token)

        # 4. Create and publish caller audio track as MICROPHONE source
        #    so the LiveKit Agent recognizes it as user audio input
        self._audio_source = rtc.AudioSource(sample_rate=_LK_SAMPLE_RATE, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("caller-audio", self._audio_source)
        publish_opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await self._room.local_participant.publish_track(track, publish_opts)

        self._running = True
        logger.info("PlivoLiveKitBridge started: room=%s", self.room_name)

    async def stream_greeting(self) -> None:
        """Stream a TTS greeting directly to Plivo — plays immediately
        without waiting for the LiveKit Agent to join the room."""
        if not self._stream_sid:
            logger.warning("Cannot stream greeting: no stream_sid yet")
            return

        if self.language == "mr":
            text = f"नमस्कार! {self.company_name} मध्ये आपले स्वागत आहे. मी माया, तुमची AI सहाय्यक. कृपया थांबा, मी तुमच्याशी लवकरच बोलते."
        else:
            text = f"Hello! Welcome to {self.company_name}. I'm Maya, your AI assistant. Please hold on while I connect."

        logger.info("Streaming greeting to Plivo for room=%s", self.room_name)
        try:
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
        except Exception:
            logger.exception("Failed to stream greeting for room=%s", self.room_name)

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

    async def _forward_agent_audio(self, audio_stream: rtc.AudioStream) -> None:
        """Subscribe to agent's audio track and forward PCM->mulaw to Plivo.

        Buffers small frames into 320-byte mulaw chunks (40ms at 8kHz)
        and skips silence to avoid flooding Plivo with empty audio.
        """
        chunks_sent = 0
        _CHUNK_SIZE = 320  # 40ms at 8kHz mulaw — Plivo's preferred chunk size
        _SILENCE_THRESHOLD = 50  # RMS below this = silence (mulaw energy)

        try:
            async for event in audio_stream:
                if not self._running:
                    break
                frame: rtc.AudioFrame = event.frame
                pcm_data = bytes(frame.data)

                if not pcm_data:
                    continue

                # Check if this frame has actual audio (not silence)
                rms = audioop.rms(pcm_data, 2)
                if rms < _SILENCE_THRESHOLD:
                    continue  # Skip silence — don't flood Plivo

                # PCM 16-bit 8kHz -> mulaw
                mulaw_data = audioop.lin2ulaw(pcm_data, 2)
                self._mulaw_out_buffer.extend(mulaw_data)

                # Send buffered chunks to Plivo
                while len(self._mulaw_out_buffer) >= _CHUNK_SIZE:
                    chunk = bytes(self._mulaw_out_buffer[:_CHUNK_SIZE])
                    self._mulaw_out_buffer = self._mulaw_out_buffer[_CHUNK_SIZE:]
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
                            logger.info("First agent audio chunk sent to Plivo (%d bytes)", _CHUNK_SIZE)
                    except Exception:
                        logger.warning("Failed to send audio to Plivo (chunk #%d)", chunks_sent)
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
        except Exception:
            logger.exception("Error forwarding agent audio to Plivo")
        finally:
            logger.info("Agent audio forwarding ended: %d chunks sent to Plivo", chunks_sent)

    def update_stream_sid(self, stream_sid: str) -> None:
        """Update the Plivo stream SID (received on 'start' event)."""
        self._stream_sid = stream_sid

    async def stop(self) -> None:
        """Leave the LiveKit room and clean up."""
        self._running = False
        if self._subscribe_task and not self._subscribe_task.done():
            self._subscribe_task.cancel()
        if self._room:
            await self._room.disconnect()
            self._room = None
        self._audio_source = None
        logger.info("PlivoLiveKitBridge stopped: room=%s", self.room_name)
