"""Deepgram streaming STT via WebSocket.

Opens a persistent WebSocket to Deepgram for the duration of a call.
Audio chunks are sent continuously; interim and final transcripts are
returned via callbacks. Supports mulaw 8kHz natively (zero conversion).

Usage:
    stt = DeepgramStreamingSTT(
        api_key="...", language="en",
        on_interim=handle_interim,
        on_final=handle_final,
        on_utterance_end=handle_end,
    )
    await stt.connect()
    # For each Plivo audio chunk:
    await stt.send_audio(mulaw_chunk)
    # When done:
    await stt.close()
"""

import asyncio
import json
import logging
from typing import Awaitable, Callable

import websockets

logger = logging.getLogger(__name__)

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"

# Words that don't count as "real speech" for barge-in purposes.
# Echo from TTS typically transcribes as these short backchannels.
BACKCHANNELS = frozenset({
    "uh", "um", "mm", "hmm", "hm", "ah", "oh",
    "yeah", "yes", "ya", "yep", "yup",
    "ok", "okay", "right", "sure", "mhm", "uh-huh",
    # Hindi
    "haan", "ji", "accha", "theek",
})


def count_real_words(transcript: str) -> int:
    """Count words that aren't backchannels."""
    words = transcript.strip().split()
    return sum(1 for w in words if w.lower().rstrip(".,!?") not in BACKCHANNELS)


class DeepgramStreamingSTT:
    """Per-session streaming STT via Deepgram WebSocket."""

    def __init__(
        self,
        api_key: str,
        language: str = "en",
        on_interim: Callable[[str], None] | None = None,
        on_final: Callable[[str], None] | None = None,
        on_utterance_end: Callable[[], Awaitable[None] | None] | None = None,
    ):
        self._api_key = api_key
        self._language = language
        self._on_interim = on_interim
        self._on_final = on_final
        self._on_utterance_end = on_utterance_end

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._receive_task: asyncio.Task | None = None
        self._connected = False

    def _build_url(self) -> str:
        """Build Deepgram WebSocket URL with query parameters."""
        # Deepgram supports mulaw 8kHz natively
        lang = {"en": "en", "hi": "hi", "mr": "hi"}.get(self._language, "en")
        params = {
            "encoding": "mulaw",
            "sample_rate": "8000",
            "channels": "1",
            "model": "nova-3",
            "language": lang,
            "interim_results": "true",
            "utterance_end_ms": "1000",
            "endpointing": "300",
            "smart_format": "true",
            "no_delay": "true",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{DEEPGRAM_WS_URL}?{query}"

    async def connect(self):
        """Open WebSocket connection and start receiving transcripts."""
        if self._connected:
            return
        url = self._build_url()
        extra_headers = {"Authorization": f"Token {self._api_key}"}
        try:
            self._ws = await websockets.connect(
                url,
                additional_headers=extra_headers,
                ping_interval=20,
                ping_timeout=10,
                open_timeout=5.0,
            )
            self._connected = True
            self._receive_task = asyncio.create_task(self._receive_loop())
            logger.info("Deepgram STT connected (lang=%s)", self._language)
        except Exception:
            logger.exception("Failed to connect to Deepgram")
            self._connected = False

    async def send_audio(self, mulaw_chunk: bytes):
        """Send raw mulaw 8kHz audio to Deepgram."""
        if not self._connected or not self._ws:
            return
        try:
            await self._ws.send(mulaw_chunk)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Deepgram WS closed while sending audio")
            self._connected = False
        except Exception:
            logger.exception("Error sending audio to Deepgram")

    async def close(self):
        """Gracefully close the Deepgram connection."""
        self._connected = False
        if self._ws:
            try:
                # Send CloseStream message per Deepgram protocol
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        logger.info("Deepgram STT closed")

    async def _receive_loop(self):
        """Background task: receive and dispatch Deepgram messages."""
        if not self._ws:
            return
        try:
            async for raw_msg in self._ws:
                try:
                    msg = json.loads(raw_msg)
                except (json.JSONDecodeError, TypeError):
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "Results":
                    await self._handle_results(msg)
                elif msg_type == "UtteranceEnd":
                    logger.debug("Deepgram: UtteranceEnd")
                    if self._on_utterance_end:
                        result = self._on_utterance_end()
                        if asyncio.iscoroutine(result):
                            await result
                elif msg_type == "Metadata":
                    logger.debug("Deepgram metadata: %s", msg.get("request_id", ""))
                elif msg_type == "Error":
                    logger.error("Deepgram error: %s", msg.get("message", msg))

        except websockets.exceptions.ConnectionClosed as e:
            logger.info("Deepgram WS closed: %s", e)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Deepgram receive loop error")
        finally:
            self._connected = False
            # Attempt one reconnect if not intentionally closed
            if self._ws is not None:
                logger.warning("Deepgram connection lost, attempting reconnect...")
                try:
                    await self.connect()
                except Exception:
                    logger.error("Deepgram reconnect failed, STT disabled for this session")

    async def _handle_results(self, msg: dict):
        """Process a Deepgram Results message."""
        channel = msg.get("channel", {})
        alternatives = channel.get("alternatives", [])
        if not alternatives:
            return

        transcript = alternatives[0].get("transcript", "").strip()
        if not transcript:
            return

        is_final = msg.get("is_final", False)
        speech_final = msg.get("speech_final", False)

        if is_final:
            logger.info("Deepgram FINAL: %s", transcript)
            if self._on_final:
                self._on_final(transcript)
        else:
            logger.debug("Deepgram interim: %s", transcript[:60])
            if self._on_interim:
                self._on_interim(transcript)
