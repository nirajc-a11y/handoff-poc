"""Real-time voice AI agent: Sarvam STT -> Groq LLM -> Sarvam TTS.

Receives raw mulaw audio chunks from Plivo Stream, detects speech pauses,
transcribes, generates LLM response, synthesizes, returns mulaw audio.

Production features:
- Barge-in: detects user speech during TTS playback and cancels output
- Streaming TTS: sentences pipelined from LLM to TTS as they arrive
- Tuned thresholds: 0.6s silence detection, 0.4s cooldown
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

import httpx

from app.config import settings
from app.core.ai_engine import ai_engine, AIResponse
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


# ---------------------------------------------------------------------------
# Speaking state for barge-in support
# ---------------------------------------------------------------------------

class SpeakingState:
    LISTENING = "listening"
    SPEAKING = "speaking"
    BARGE_IN = "barge_in"


class VoiceAISession:
    """One AI conversation session for a phone call."""

    def __init__(self, tenant_id: str, conv_id: str, language: str = "en", speaker: str = "ritu"):
        self.tenant_id = tenant_id
        self.conv_id = conv_id
        self.language = language
        self.speaker = speaker
        self.conversation_history: list[dict] = []
        self.turn_count = 0
        self.audio_buffer = bytearray()
        self.silence_frames = 0
        self._greeting_sent = False
        self.should_escalate = False
        self.should_end_call = False
        self._cooldown_remaining = 0

        # Silence detection (mulaw 8kHz, thresholds are 16-bit PCM RMS values)
        self.silence_threshold = 200   # RMS below this = silence (16-bit PCM scale)
        self.silence_duration_frames = 4800  # ~0.6 seconds (industry standard)
        self.min_speech_frames = 2400  # ~0.3 seconds

        # Barge-in state
        self._state = SpeakingState.LISTENING
        self._barge_in_event = asyncio.Event()
        self._barge_in_energy_threshold = 400  # Higher than silence to reject echo
        self._barge_in_consecutive = 0
        self._barge_in_required_frames = 3     # ~60ms of speech to confirm

        # Echo guard: phone lines echo AI speech back as short mono-syllabic
        # noise that STT transcribes as "Yes", "Yeah", etc. We discard the
        # first utterance after TTS if it matches these patterns.
        self._post_tts_guard = False
        self._echo_phrases = {
            "yes", "yes.", "yeah", "yeah.", "ya", "ok", "okay", "hmm",
            "hm", "uh", "um", "ah", "mm", "right", "sure",
            "yes yes yes", "yes yes", "yes,", "yes, yes", "yes, yes, yes",
            "हो", "हो.", "हां", "हां.", "हम्म", "अच्छा",
        }

    # ------------------------------------------------------------------
    # Public properties for backward compat
    # ------------------------------------------------------------------

    @property
    def is_speaking(self) -> bool:
        return self._state == SpeakingState.SPEAKING

    @is_speaking.setter
    def is_speaking(self, value: bool):
        if value:
            self.start_speaking()
        else:
            self._state = SpeakingState.LISTENING

    @property
    def barge_in_requested(self) -> bool:
        return self._barge_in_event.is_set()

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def start_speaking(self):
        """Transition to SPEAKING state (TTS playback starting)."""
        self._state = SpeakingState.SPEAKING
        self._barge_in_event.clear()
        self._barge_in_consecutive = 0

    def finish_speaking(self):
        """Mark TTS playback as complete, discard echo, and start cooldown."""
        self.audio_buffer.clear()
        self.silence_frames = 0
        self._cooldown_remaining = 4800  # ~0.6 seconds at 8kHz
        self._state = SpeakingState.LISTENING
        self._barge_in_event.clear()
        self._barge_in_consecutive = 0
        self._post_tts_guard = True  # Enable echo guard for next utterance

    # ------------------------------------------------------------------
    # Audio input
    # ------------------------------------------------------------------

    def add_audio(self, mulaw_chunk: bytes) -> bool:
        """Add audio chunk. Returns True if speech pause detected.

        During SPEAKING state: monitors for barge-in (user interruption).
        During BARGE_IN state: buffers audio, detects speech pause.
        During LISTENING state: normal speech pause detection.
        """
        pcm = audioop.ulaw2lin(mulaw_chunk, 2)
        rms_energy = audioop.rms(pcm, 2)

        # --- SPEAKING: detect barge-in ---
        if self._state == SpeakingState.SPEAKING:
            if rms_energy > self._barge_in_energy_threshold:
                self._barge_in_consecutive += 1
                if self._barge_in_consecutive >= self._barge_in_required_frames:
                    logger.info("Barge-in detected (energy=%d, consecutive=%d)",
                                rms_energy, self._barge_in_consecutive)
                    self._state = SpeakingState.BARGE_IN
                    self._barge_in_event.set()
                    # Start buffering the interrupting speech
                    self.audio_buffer.clear()
                    self.audio_buffer.extend(mulaw_chunk)
                    self.silence_frames = 0
                    self._cooldown_remaining = 0
            else:
                self._barge_in_consecutive = 0
            return False

        # --- BARGE_IN: buffer audio, detect pause ---
        if self._state == SpeakingState.BARGE_IN:
            self.audio_buffer.extend(mulaw_chunk)
            if rms_energy < self.silence_threshold:
                self.silence_frames += len(mulaw_chunk)
            else:
                self.silence_frames = 0
            return (len(self.audio_buffer) > self.min_speech_frames
                    and self.silence_frames >= self.silence_duration_frames)

        # --- LISTENING: normal path ---
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= len(mulaw_chunk)
            return False
        self.audio_buffer.extend(mulaw_chunk)
        if rms_energy < self.silence_threshold:
            self.silence_frames += len(mulaw_chunk)
        else:
            self.silence_frames = 0
        return (len(self.audio_buffer) > self.min_speech_frames
                and self.silence_frames >= self.silence_duration_frames)

    def flush_buffer(self):
        """Discard any buffered audio (call after TTS playback to avoid echo)."""
        self.audio_buffer.clear()
        self.silence_frames = 0

    # ------------------------------------------------------------------
    # Turn processing: STT -> LLM (streaming) -> TTS (streaming)
    # ------------------------------------------------------------------

    async def process_turn(self, db_session=None, on_audio=None) -> bytes | None:
        """Process buffered audio: STT -> LLM -> TTS.

        Args:
            db_session: Async SQLAlchemy session for saving messages.
            on_audio: Optional async callback for streaming TTS. When provided,
                mulaw chunks are sent via on_audio(chunk) as they arrive.
                Returns b"" to signal audio was streamed.
                When None, returns full mulaw audio (legacy path).

        IMPORTANT: is_speaking remains True after return -- the caller must
        call finish_speaking() after audio playback completes.
        """
        if len(self.audio_buffer) < self.min_speech_frames:
            self.audio_buffer.clear()
            self.silence_frames = 0
            return None

        self.start_speaking()
        audio_data = bytes(self.audio_buffer)
        self.audio_buffer.clear()
        self.silence_frames = 0

        try:
            wav_data = _mulaw_to_wav(audio_data)
            transcript = await sarvam.transcribe(wav_data, language=self.language)

            if not transcript.strip():
                self._state = SpeakingState.LISTENING
                return None

            # Echo guard: discard short phantom transcripts from phone-line echo
            if self._post_tts_guard:
                self._post_tts_guard = False  # Only applies to first utterance after TTS
                cleaned = transcript.strip().lower().rstrip(".!,")
                words = cleaned.split()
                if len(words) <= 4 and cleaned in self._echo_phrases:
                    logger.info("Echo guard: discarding likely echo '%s'", transcript.strip())
                    self._state = SpeakingState.LISTENING
                    return None

            logger.info("Turn %d - Customer: %s", self.turn_count, transcript)

            # Save customer message
            if db_session and self.conv_id:
                await self._save_message(db_session, "customer", transcript, {"source": "sarvam_stt", "turn": self.turn_count})

            # --- Streaming LLM + sentence-pipeline TTS ---
            if on_audio:
                try:
                    full_response = ""
                    last_ai_response = None

                    async for sentence, ai_resp in ai_engine.process_message_stream(
                        customer_message=transcript,
                        conversation_history=self.conversation_history,
                        language=self.language,
                    ):
                        if self._barge_in_event.is_set():
                            logger.info("Barge-in: stopping LLM+TTS pipeline")
                            if sentence:
                                full_response += (" " if full_response else "") + sentence
                            break

                        if sentence:
                            full_response += (" " if full_response else "") + sentence

                        if ai_resp is not None:
                            last_ai_response = ai_resp

                        # Stream this sentence to TTS immediately
                        if sentence:
                            try:
                                async for chunk in sarvam.synthesize_stream(sentence, self.language, self.speaker):
                                    if self._barge_in_event.is_set():
                                        logger.info("Barge-in: stopping TTS stream mid-sentence")
                                        break
                                    await on_audio(chunk)
                            except Exception:
                                logger.warning("Streaming TTS failed for sentence, trying batch")
                                try:
                                    tts_audio = await sarvam.synthesize(sentence, self.language, self.speaker)
                                    mulaw_audio = _wav_to_mulaw(tts_audio)
                                    await on_audio(mulaw_audio)
                                except Exception:
                                    logger.exception("Batch TTS also failed for sentence")

                    # Update conversation state
                    ai_text = full_response.strip()
                    if ai_text:
                        logger.info("Turn %d - AI: %s (streamed)", self.turn_count, ai_text[:80])
                        self.conversation_history.append({"role": "user", "content": transcript})
                        self.conversation_history.append({"role": "assistant", "content": ai_text})
                        self.turn_count += 1

                        if db_session and self.conv_id:
                            confidence = last_ai_response.confidence if last_ai_response else 0.85
                            should_esc = last_ai_response.should_escalate if last_ai_response else False
                            await self._save_message(db_session, "ai", ai_text, {
                                "confidence": confidence,
                                "should_escalate": should_esc,
                                "turn": self.turn_count,
                            })

                        if last_ai_response:
                            self.should_escalate = last_ai_response.should_escalate
                            self.should_end_call = last_ai_response.should_end_call

                    return b""  # signal: audio streamed via callback

                except Exception:
                    logger.exception("Streaming pipeline failed, falling back to batch")
                    # Fall through to batch path

            # --- Batch fallback (non-streaming or streaming failure) ---
            ai_response = await ai_engine.process_message(
                customer_message=transcript,
                conversation_history=self.conversation_history,
                language=self.language,
            )
            logger.info("Turn %d - AI: %s (escalate=%s)", self.turn_count, ai_response.text[:80], ai_response.should_escalate)

            self.conversation_history.append({"role": "user", "content": transcript})
            self.conversation_history.append({"role": "assistant", "content": ai_response.text})
            self.turn_count += 1

            if db_session and self.conv_id:
                await self._save_message(db_session, "ai", ai_response.text, {
                    "confidence": ai_response.confidence,
                    "should_escalate": ai_response.should_escalate,
                    "turn": self.turn_count,
                })

            self.should_escalate = ai_response.should_escalate
            self.should_end_call = ai_response.should_end_call

            # TTS -- truncate long responses to keep latency low
            tts_text = ai_response.text
            if len(tts_text) > 300:
                cut = tts_text[:300].rfind(".")
                tts_text = tts_text[:cut + 1] if cut > 100 else tts_text[:300]

            tts_audio = await sarvam.synthesize(tts_text, self.language, self.speaker)
            mulaw_audio = _wav_to_mulaw(tts_audio)
            return mulaw_audio

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Sarvam API call failed in turn %d (HTTP %d): %s. Check SARVAM_API_KEY.",
                self.turn_count, exc.response.status_code, exc.response.text[:200],
            )
            self._state = SpeakingState.LISTENING
            return None
        except Exception:
            logger.exception("Unexpected error in voice AI turn %d", self.turn_count)
            self._state = SpeakingState.LISTENING
            return None

    # ------------------------------------------------------------------
    # Greeting
    # ------------------------------------------------------------------

    async def stream_greeting(self, on_audio) -> None:
        """Stream greeting TTS audio via callback (~500ms to first audio).

        Uses synthesize_stream for low latency. Falls back to batch if needed.
        Leaves is_speaking=True -- caller must call finish_speaking().
        """
        if self._greeting_sent:
            return
        self._greeting_sent = True
        self.start_speaking()

        greeting = (
            "Demo Corp विक्री विभागात आपले स्वागत आहे. मी तुमचा AI सहाय्यक आहे. मी तुम्हाला कशी मदत करू शकतो?"
            if self.language == "mr" else
            "Welcome to Demo Corp. I'm your AI assistant. How can I help you today?"
        )
        try:
            total = 0
            async for chunk in sarvam.synthesize_stream(greeting, self.language, self.speaker):
                if self._barge_in_event.is_set():
                    logger.info("Barge-in during greeting, stopping")
                    break
                await on_audio(chunk)
                total += len(chunk)
            logger.info("Greeting streamed: %d bytes mulaw", total)
        except Exception:
            logger.warning("Streaming greeting failed, trying batch fallback")
            try:
                tts_audio = await sarvam.synthesize(greeting, self.language, self.speaker)
                mulaw_audio = _wav_to_mulaw(tts_audio)
                await on_audio(mulaw_audio)
                logger.info("Greeting batch fallback: %d bytes mulaw", len(mulaw_audio))
            except Exception:
                logger.exception("Greeting TTS completely failed")

    async def get_greeting_audio(self) -> bytes | None:
        """Generate greeting TTS audio (batch fallback for non-streaming callers)."""
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
            mulaw_audio = _wav_to_mulaw(tts_audio)
            logger.info("Greeting audio generated: %d bytes WAV -> %d bytes mulaw", len(tts_audio), len(mulaw_audio))
            return mulaw_audio
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Sarvam TTS greeting failed (HTTP %d): %s. Check SARVAM_API_KEY.",
                exc.response.status_code, exc.response.text[:200],
            )
            return None
        except Exception:
            logger.exception("Unexpected error generating greeting audio")
            return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

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
