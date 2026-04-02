"""Real-time voice AI agent: Sarvam STT -> Groq LLM -> Sarvam TTS.

Receives raw mulaw audio chunks from Plivo Stream, detects speech pauses,
transcribes, generates LLM response, synthesizes, returns mulaw audio.
"""

import asyncio
import io

try:
    import audioop  # available in Python <=3.12
except ModuleNotFoundError:
    import audioop_lts as audioop  # type: ignore[no-redef]  # Python 3.13+
import logging
import uuid
import wave
from datetime import datetime, timezone

from app.config import settings
from app.core.ai_engine import ai_engine
from app.livekit import sarvam

logger = logging.getLogger(__name__)


def _mulaw_to_wav(mulaw_data: bytes, sample_rate: int = 8000) -> bytes:
    """Convert mulaw audio bytes to WAV format for Sarvam STT."""
    pcm_data = audioop.ulaw2lin(mulaw_data, 2)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def _wav_to_mulaw(wav_data: bytes) -> bytes:
    """Convert WAV audio to mulaw for Plivo Stream playback."""
    buf = io.BytesIO(wav_data)
    with wave.open(buf, "rb") as wf:
        pcm_data = wf.readframes(wf.getnframes())
        sample_rate = wf.getframerate()
        sample_width = wf.getsampwidth()
    if sample_rate != 8000:
        pcm_data, _ = audioop.ratecv(pcm_data, sample_width, 1, sample_rate, 8000, None)
    if sample_width != 2:
        pcm_data = audioop.lin2lin(pcm_data, sample_width, 2)
    return audioop.lin2ulaw(pcm_data, 2)


class VoiceAISession:
    """One AI conversation session for a phone call."""

    def __init__(self, tenant_id: str, conv_id: str, language: str = "en", speaker: str = "meera"):
        self.tenant_id = tenant_id
        self.conv_id = conv_id
        self.language = language
        self.speaker = speaker
        self.conversation_history: list[dict] = []
        self.turn_count = 0
        self.audio_buffer = bytearray()
        self.silence_frames = 0
        self.is_speaking = False
        self._greeting_sent = False
        self.should_escalate = False

        # Silence detection (mulaw 8kHz)
        self.silence_threshold = 10
        self.silence_duration_frames = 24000  # ~3 seconds
        self.min_speech_frames = 4000  # ~0.5 seconds

    def add_audio(self, mulaw_chunk: bytes) -> bool:
        """Add audio chunk. Returns True if speech pause detected."""
        if self.is_speaking:
            return False
        self.audio_buffer.extend(mulaw_chunk)
        avg_energy = sum(abs(b - 128) for b in mulaw_chunk) / max(len(mulaw_chunk), 1)
        if avg_energy < self.silence_threshold:
            self.silence_frames += len(mulaw_chunk)
        else:
            self.silence_frames = 0
        return len(self.audio_buffer) > self.min_speech_frames and self.silence_frames >= self.silence_duration_frames

    async def process_turn(self, db_session=None) -> bytes | None:
        """Process buffered audio: STT -> LLM -> TTS. Returns mulaw audio."""
        if len(self.audio_buffer) < self.min_speech_frames:
            self.audio_buffer.clear()
            self.silence_frames = 0
            return None

        self.is_speaking = True
        audio_data = bytes(self.audio_buffer)
        self.audio_buffer.clear()
        self.silence_frames = 0

        try:
            wav_data = _mulaw_to_wav(audio_data)
            transcript = await sarvam.transcribe(wav_data, language=self.language)

            if not transcript.strip():
                self.is_speaking = False
                return None

            logger.info("Turn %d - Customer: %s", self.turn_count, transcript)

            # Save customer message
            if db_session and self.conv_id:
                await self._save_message(db_session, "customer", transcript, {"source": "sarvam_stt", "turn": self.turn_count})

            # LLM
            ai_response = await ai_engine.process_message(
                customer_message=transcript,
                conversation_history=self.conversation_history,
                language=self.language,
            )
            logger.info("Turn %d - AI: %s (escalate=%s)", self.turn_count, ai_response.text[:80], ai_response.should_escalate)

            self.conversation_history.append({"role": "user", "content": transcript})
            self.conversation_history.append({"role": "assistant", "content": ai_response.text})
            self.turn_count += 1

            # Save AI message
            if db_session and self.conv_id:
                await self._save_message(db_session, "ai", ai_response.text, {
                    "confidence": ai_response.confidence,
                    "should_escalate": ai_response.should_escalate,
                    "turn": self.turn_count,
                })

            self.should_escalate = ai_response.should_escalate

            # TTS
            tts_audio = await sarvam.synthesize(ai_response.text, self.language, self.speaker)
            mulaw_audio = _wav_to_mulaw(tts_audio)
            self.is_speaking = False
            return mulaw_audio

        except Exception:
            logger.exception("Error in voice AI turn %d", self.turn_count)
            self.is_speaking = False
            return None

    async def get_greeting_audio(self) -> bytes | None:
        """Generate greeting TTS audio."""
        if self._greeting_sent:
            return None
        self._greeting_sent = True
        greeting = (
            "Demo Corp विक्री विभागात आपले स्वागत आहे. मी तुमचा AI सहाय्यक आहे. मी तुम्हाला कशी मदत करू शकतो?"
            if self.language == "mr" else
            "Welcome to Demo Corp. I'm your AI assistant. How can I help you today?"
        )
        try:
            tts_audio = await sarvam.synthesize(greeting, self.language, self.speaker)
            return _wav_to_mulaw(tts_audio)
        except Exception:
            logger.exception("Failed to generate greeting")
            return None

    async def _save_message(self, db, sender_type: str, content: str, metadata: dict):
        try:
            from app.db.models.message import Message
            msg = Message(
                tenant_id=uuid.UUID(self.tenant_id),
                conversation_id=uuid.UUID(self.conv_id),
                sender_type=sender_type,
                content_type="text",
                content=content,
                metadata_=metadata,
            )
            db.add(msg)
            await db.flush()
        except Exception:
            logger.exception("Failed to save message")
