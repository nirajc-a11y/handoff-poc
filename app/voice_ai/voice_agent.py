"""Real-time voice AI agent: Sarvam STT -> Groq LLM -> Sarvam TTS.

Receives raw mulaw audio chunks from Plivo Stream, detects speech pauses,
transcribes, generates LLM response, synthesizes, returns mulaw audio.

Production features:
- Barge-in: detects user speech during TTS playback and cancels output
- Streaming TTS: sentences pipelined from LLM to TTS as they arrive
- Tuned thresholds: 0.6s silence detection, 0.3s cooldown, 3s echo guard window
"""

import asyncio
import io
import time

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
from app.voice_ai import sarvam

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

    def __init__(self, tenant_id: str, conv_id: str, language: str = "en", speaker: str = "ritu",
                 tenant_name: str = "Demo Corp", system_prompt: str | None = None):
        self.tenant_id = tenant_id
        self.conv_id = conv_id
        self.language = language
        self.speaker = speaker
        self.tenant_name = tenant_name
        self.system_prompt = system_prompt
        self.conversation_history: list[dict] = []
        self.turn_count = 0
        self.audio_buffer = bytearray()
        self.silence_frames = 0
        self._greeting_sent = False
        self.should_escalate = False
        self.should_end_call = False
        self._cooldown_remaining = 0
        self._tts_finished_at: float = 0.0  # monotonic time when last TTS playback ended

        # Silence detection (mulaw 8kHz, thresholds are 16-bit PCM RMS values)
        self.silence_threshold = 400   # RMS below this = silence (phone line noise is 200-300)
        self.silence_duration_frames = 4800  # ~0.6 seconds (industry standard)
        self.min_speech_frames = 3200  # ~0.4 seconds (reject very short noise bursts)

        # Speech onset detection — require consecutive speech frames before buffering.
        # Prevents sporadic noise spikes from triggering STT calls.
        self._speech_started = False
        self._speech_onset_count = 0
        self._speech_onset_required = 5  # ~100ms of consecutive speech to confirm onset

        # Barge-in state
        self._state = SpeakingState.LISTENING
        self._barge_in_event = asyncio.Event()
        self._barge_in_energy_threshold = 600  # Higher than silence (400) to reject echo
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

        # Max audio buffer: 5 seconds at 8kHz mulaw (prevents runaway buffering on noisy lines)
        self._max_buffer_bytes = 40000

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
    # Supervisor interaction
    # ------------------------------------------------------------------

    def inject_supervisor_hint(self, message: str):
        """Inject supervisor guidance into conversation history.

        The AI will see this as a system-level instruction and incorporate
        it in the next response. The customer never hears this directly.
        """
        hint = {"role": "system", "content": f"[Supervisor guidance]: {message}"}
        self.conversation_history.append(hint)
        logger.info("Supervisor hint injected: '%s' (turn %d)", message[:80], self.turn_count)

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
        self._cooldown_remaining = 2400  # ~0.3s at 8kHz (safety margin; playback wait handles most echo)
        self._state = SpeakingState.LISTENING
        self._barge_in_event.clear()
        self._barge_in_consecutive = 0
        self._post_tts_guard = True  # Enable echo guard for next utterance
        self._tts_finished_at = time.monotonic()
        self._speech_started = False
        self._speech_onset_count = 0

    def reset_listening(self):
        """Lightweight reset after a null turn (no TTS was played).

        Unlike finish_speaking(), this does NOT:
        - Apply cooldown (no echo to wait for)
        - Enable echo guard (no TTS output to echo)
        - Clear audio_buffer (preserves any accumulated speech)
        """
        self.silence_frames = 0
        self._state = SpeakingState.LISTENING
        self._barge_in_event.clear()
        self._barge_in_consecutive = 0
        # If buffer has content (e.g. from barge-in), speech is already confirmed
        self._speech_started = len(self.audio_buffer) > 0
        self._speech_onset_count = 0

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

        # Speech onset detection: require consecutive speech frames before
        # buffering. This prevents sporadic noise spikes from triggering
        # STT calls (e.g., phone-line crackle transcribed as "Telugu").
        if not self._speech_started:
            if rms_energy >= self.silence_threshold:
                self._speech_onset_count += 1
                if self._speech_onset_count >= self._speech_onset_required:
                    self._speech_started = True
                    self.audio_buffer.extend(mulaw_chunk)
            else:
                self._speech_onset_count = 0
            return False

        # Speech confirmed — buffer and detect pause
        self.audio_buffer.extend(mulaw_chunk)
        if rms_energy < self.silence_threshold:
            self.silence_frames += len(mulaw_chunk)
        else:
            self.silence_frames = 0

        # Cap buffer to prevent runaway accumulation on noisy lines.
        if len(self.audio_buffer) >= self._max_buffer_bytes:
            logger.info("Buffer cap reached (%d bytes), forcing speech pause", len(self.audio_buffer))
            return True

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

        # Check average energy — skip STT if buffer is mostly silence/noise
        pcm_all = audioop.ulaw2lin(bytes(self.audio_buffer), 2)
        avg_rms = audioop.rms(pcm_all, 2)
        if avg_rms < self.silence_threshold:
            logger.debug("Skipping STT: avg RMS %d below threshold %d", avg_rms, self.silence_threshold)
            self.audio_buffer.clear()
            self.silence_frames = 0
            return None

        # Check speech ratio — require that >=15% of frames have energy above
        # threshold. Phone noise produces occasional spikes but not sustained energy.
        chunk_size = 320  # 20ms frames
        raw = bytes(self.audio_buffer)
        speech_frames = 0
        total_frames = 0
        for i in range(0, len(raw), chunk_size):
            frame = raw[i:i + chunk_size]
            if len(frame) < 160:
                break
            total_frames += 1
            frame_pcm = audioop.ulaw2lin(frame, 2)
            if audioop.rms(frame_pcm, 2) >= self.silence_threshold:
                speech_frames += 1
        if total_frames > 0 and speech_frames / total_frames < 0.25:
            logger.debug("Skipping STT: speech ratio %.1f%% below 25%% (%d/%d frames)",
                         speech_frames / total_frames * 100, speech_frames, total_frames)
            self.audio_buffer.clear()
            self.silence_frames = 0
            return None

        self.start_speaking()
        audio_data = bytes(self.audio_buffer)
        self.audio_buffer.clear()
        self.silence_frames = 0

        # Trim trailing silence (from the 0.6s silence detection window).
        # Sending silence to STT increases hallucination risk.
        trim_chunk = 160  # 20ms frames
        while len(audio_data) > trim_chunk:
            tail_pcm = audioop.ulaw2lin(audio_data[-trim_chunk:], 2)
            if audioop.rms(tail_pcm, 2) >= self.silence_threshold:
                break
            audio_data = audio_data[:-trim_chunk]
        if len(audio_data) < self.min_speech_frames:
            self._state = SpeakingState.LISTENING
            return None

        try:
            wav_data = _mulaw_to_wav(audio_data)
            transcript = await sarvam.transcribe(wav_data, language=self.language)

            if not transcript.strip():
                self._state = SpeakingState.LISTENING
                return None

            # --- STT hallucination detection ---
            # Whisper-family models hallucinate repetitive text on noise/silence.
            words_raw = transcript.strip().lower().replace(",", " ").replace(".", " ").split()

            # 1) Single-word hallucination: STT often returns a random word
            #    ("But", "The", "So") from noise. Only allow plausible 1-word utterances.
            _valid_single_words = {
                "hello", "hi", "hey", "yes", "no", "yeah", "nah", "help",
                "thanks", "bye", "okay", "ok", "please", "stop", "wait",
                "नमस्ते", "हां", "नहीं", "हेलो", "धन्यवाद",
            }
            if len(words_raw) == 1 and words_raw[0].rstrip(".,!?") not in _valid_single_words:
                logger.info("Hallucination guard: discarding single-word STT '%s'", transcript.strip())
                self._state = SpeakingState.LISTENING
                return None

            # 2) Repetitive hallucination: same word >60% of transcript
            if len(words_raw) > 4:
                from collections import Counter
                word_counts = Counter(words_raw)
                most_common_word, most_common_count = word_counts.most_common(1)[0]
                if most_common_count / len(words_raw) > 0.6:
                    logger.info("Hallucination guard: discarding repetitive STT ('%s' x%d in %d words)",
                                most_common_word, most_common_count, len(words_raw))
                    self._state = SpeakingState.LISTENING
                    return None

            # Echo guard: discard short phantom transcripts from phone-line echo.
            # Only active within 3s of TTS ending — real echo decays in <1s,
            # the extra margin covers slow phone networks.
            if self._post_tts_guard:
                echo_age = time.monotonic() - self._tts_finished_at
                if echo_age > 3.0:
                    # Guard expired — treat all speech as genuine
                    logger.debug("Echo guard expired (%.1fs since TTS), accepting transcript", echo_age)
                    self._post_tts_guard = False
                else:
                    self._post_tts_guard = False  # One-shot: only first utterance after TTS
                    cleaned = transcript.strip().lower().rstrip(".!,")
                    words = cleaned.split()
                    # Check short echo phrases
                    if len(words) <= 4 and cleaned in self._echo_phrases:
                        logger.info("Echo guard: discarding likely echo '%s' (%.1fs after TTS)",
                                    transcript.strip(), echo_age)
                        self._state = SpeakingState.LISTENING
                        return None
                    # Also discard if it's entirely echo-like words (any length)
                    echo_words = {"yes", "yeah", "ya", "ok", "okay", "hmm", "hm", "uh", "um", "ah", "mm",
                                  "right", "sure", "हो", "हां", "हम्म", "अच्छा"}
                    if all(w.rstrip(".,!?") in echo_words for w in words):
                        logger.info("Echo guard: discarding all-echo transcript '%s' (%.1fs after TTS)",
                                    transcript.strip()[:80], echo_age)
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
                        system_prompt=self.system_prompt,
                        company_name=self.tenant_name,
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
                system_prompt=self.system_prompt,
                company_name=self.tenant_name,
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
            f"{self.tenant_name} विक्री विभागात आपले स्वागत आहे. मी तुमचा AI सहाय्यक आहे. मी तुम्हाला कशी मदत करू शकतो?"
            if self.language == "mr" else
            f"Welcome to {self.tenant_name}. I'm your AI assistant. How can I help you today?"
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
            f"{self.tenant_name} विक्री विभागात आपले स्वागत आहे. मी तुमचा AI सहाय्यक आहे. मी तुम्हाला कशी मदत करू शकतो?"
            if self.language == "mr" else
            f"Welcome to {self.tenant_name}. I'm your AI assistant. How can I help you today?"
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
