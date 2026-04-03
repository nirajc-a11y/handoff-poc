"""LiveKit TTS plugin wrapping the Sarvam Bulbul v3 streaming API.

Reuses the existing shared httpx connection pool from sarvam.py.
Converts Sarvam's native mulaw 8kHz output to PCM for LiveKit,
which handles final encoding/transport to participants.
"""

from __future__ import annotations

import audioop
import logging
from dataclasses import dataclass

from livekit.agents import tts

from app.config import settings
from app.voice_ai.sarvam import synthesize_stream, V2_TO_V3_SPEAKER

logger = logging.getLogger(__name__)

_SARVAM_SAMPLE_RATE = 8000
_OUTPUT_SAMPLE_RATE = 24000


@dataclass
class _SarvamTTSOptions:
    language: str = "en"
    speaker: str = "ritu"
    pace: float = 1.0


class SarvamTTS(tts.TTS):
    """LiveKit-compatible TTS plugin backed by Sarvam Bulbul v3."""

    def __init__(
        self,
        *,
        language: str = "en",
        speaker: str = "ritu",
        pace: float = 1.0,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=_OUTPUT_SAMPLE_RATE,
            num_channels=1,
        )
        self._opts = _SarvamTTSOptions(
            language=language,
            speaker=V2_TO_V3_SPEAKER.get(speaker, speaker),
            pace=pace,
        )

    def synthesize(self, text: str, *, conn_options=None) -> "SarvamChunkedStream":
        return SarvamChunkedStream(tts=self, input_text=text, conn_options=conn_options or tts.APIConnectOptions())

    def stream(self, *, conn_options=None) -> "SarvamSynthesizeStream":
        return SarvamSynthesizeStream(tts=self, conn_options=conn_options or tts.APIConnectOptions())


class SarvamChunkedStream(tts.ChunkedStream):
    """Non-streaming synthesis — collects all audio then emits frames."""

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id="sarvam-chunked",
            sample_rate=_OUTPUT_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )
        output_emitter.start_segment(segment_id="seg-0")

        text = self.input_text.strip()
        if len(text) >= 2:
            opts = self._tts._opts  # type: ignore[attr-defined]
            buf = bytearray()
            try:
                async for chunk in synthesize_stream(
                    text=text,
                    language=opts.language,
                    speaker=opts.speaker,
                    pace=opts.pace,
                ):
                    buf.extend(chunk)
            except Exception:
                logger.warning("Sarvam TTS chunked failed for text: %s", text[:50])

            if buf:
                pcm_8k = audioop.ulaw2lin(bytes(buf), 2)
                pcm_24k, _ = audioop.ratecv(pcm_8k, 2, 1, _SARVAM_SAMPLE_RATE, _OUTPUT_SAMPLE_RATE, None)
                output_emitter.push(pcm_24k)

        output_emitter.end_segment()
        output_emitter.flush()


class SarvamSynthesizeStream(tts.SynthesizeStream):
    """Streaming synthesis — yields PCM frames as Sarvam chunks arrive."""

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id="sarvam-stream",
            sample_rate=_OUTPUT_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
            stream=True,
        )

        opts = self._tts._opts  # type: ignore[attr-defined]
        seg_idx = 0

        async for text_input in self._input_ch:
            if not isinstance(text_input, str) or not text_input.strip():
                continue

            # Skip text that Sarvam will reject (no real characters)
            cleaned = text_input.strip()
            if len(cleaned) < 2:
                continue

            output_emitter.start_segment(segment_id=f"seg-{seg_idx}")
            seg_idx += 1

            try:
                async for mulaw_chunk in synthesize_stream(
                    text=cleaned,
                    language=opts.language,
                    speaker=opts.speaker,
                    pace=opts.pace,
                ):
                    pcm_8k = audioop.ulaw2lin(mulaw_chunk, 2)
                    pcm_24k, _ = audioop.ratecv(pcm_8k, 2, 1, _SARVAM_SAMPLE_RATE, _OUTPUT_SAMPLE_RATE, None)
                    output_emitter.push(pcm_24k)
            except Exception:
                logger.warning("Sarvam TTS stream failed for text: %s", cleaned[:50])

            output_emitter.end_segment()

        output_emitter.flush()
