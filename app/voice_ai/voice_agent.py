"""Real-time voice AI agent: Deepgram STT -> Groq LLM -> Sarvam TTS.

Receives raw mulaw audio chunks from Plivo Stream, streams them to
Deepgram for real-time transcription, generates LLM response, synthesizes
TTS, and sends audio back.

Production features:
- Deepgram streaming STT: continuous transcription, no audio cropping
- MinWords barge-in: interim transcripts detect real user speech during TTS
- Silero VAD: speech onset detection for Marathi batch STT fallback
- Streaming TTS: sentences pipelined from LLM to TTS as they arrive
- Echo guard: post-TTS phrase filtering for phone-line echo artifacts
"""

import asyncio
import io
import time

try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop  # type: ignore[no-redef]
import logging
import uuid
import wave

import httpx

from app.config import settings
from app.core.ai_engine import ai_engine, AIResponse
from app.voice_ai import sarvam
from app.voice_ai.deepgram_stt import DeepgramStreamingSTT, count_real_words
from app.voice_ai.vad import VADProcessor

logger = logging.getLogger(__name__)

# Minimum real words in interim transcript to confirm barge-in.
# Echo typically transcribes as 0-2 backchannel words.
MIN_BARGEIN_WORDS = 3


def _mulaw_to_wav(mulaw_data: bytes, sample_rate: int = 8000) -> bytes:
    """Convert mulaw audio bytes to WAV format for batch STT fallback."""
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
    """One AI conversation session for a phone call.

    Uses Deepgram streaming STT for real-time transcription (en, hi).
    Falls back to batch STT (Sarvam saaras) for Marathi.
    """

    def __init__(self, tenant_id: str, conv_id: str, language: str = "en", speaker: str = "ritu",
                 tenant_name: str = "Demo Corp", system_prompt: str | None = None,
                 endpointing_profile: str = settings.vad_endpointing_profile):
        self.tenant_id = tenant_id
        self.conv_id = conv_id
        self.language = language
        self.speaker = speaker
        self.tenant_name = tenant_name
        self.system_prompt = system_prompt
        self.conversation_history: list[dict] = []
        self.turn_count = 0
        self._greeting_sent = False
        self.should_escalate = False
        self.should_end_call = False
        self._tts_finished_at: float = 0.0

        # Deepgram streaming STT
        self._deepgram: DeepgramStreamingSTT | None = None
        self._use_streaming_stt = bool(settings.deepgram_api_key) and language in ("en", "hi")
        self._final_transcripts: list[str] = []
        self._pending_turn = asyncio.Event()  # Set when Deepgram signals utterance end

        # Barge-in state
        self._state = SpeakingState.LISTENING
        self._barge_in_event = asyncio.Event()

        # Echo guard: discard short backchannel transcripts right after TTS
        self._post_tts_guard = False
        self._echo_phrases = {
            "yes", "yes.", "yeah", "yeah.", "ya", "ok", "okay", "hmm",
            "hm", "uh", "um", "ah", "mm", "right", "sure",
            "yes yes yes", "yes yes", "yes,", "yes, yes", "yes, yes, yes",
            "हो", "हो.", "हां", "हां.", "हम्म", "अच्छा",
        }

        # --- Batch STT fallback (Marathi, or if Deepgram unavailable) ---
        self._vad = VADProcessor(
            profile=endpointing_profile,
            threshold=settings.vad_threshold,
        )
        self.audio_buffer = bytearray()
        self._speech_started = False
        self._speech_onset_count = 0
        self._silence_vad_frames = 0
        self._cooldown_remaining = 0
        self._max_buffer_bytes = 40000

    # ------------------------------------------------------------------
    # Deepgram lifecycle
    # ------------------------------------------------------------------

    async def start_deepgram(self):
        """Open Deepgram streaming STT connection."""
        if not self._use_streaming_stt:
            return
        self._deepgram = DeepgramStreamingSTT(
            api_key=settings.deepgram_api_key,
            language=self.language,
            on_interim=self._on_deepgram_interim,
            on_final=self._on_deepgram_final,
            on_utterance_end=self._on_deepgram_utterance_end,
        )
        await self._deepgram.connect()

    async def stop_deepgram(self):
        """Close Deepgram connection."""
        if self._deepgram:
            await self._deepgram.close()
            self._deepgram = None

    def _on_deepgram_interim(self, transcript: str):
        """Called on each interim transcript from Deepgram."""
        # MinWords barge-in: during SPEAKING, check if user is really talking
        if self._state == SpeakingState.SPEAKING:
            real_words = count_real_words(transcript)
            if real_words >= MIN_BARGEIN_WORDS:
                logger.info("MinWords barge-in: '%s' (%d real words)", transcript[:60], real_words)
                self._state = SpeakingState.BARGE_IN
                self._barge_in_event.set()

    def _on_deepgram_final(self, transcript: str):
        """Called when Deepgram finalizes a transcript segment."""
        if not transcript.strip():
            return
        # During SPEAKING without barge-in, Deepgram transcribes TTS echo
        # from the phone line. Discard these -- they're the AI's own voice.
        if self._state == SpeakingState.SPEAKING and not self._barge_in_event.is_set():
            logger.info("Discarding echo transcript during TTS: '%s'", transcript.strip()[:60])
            return
        self._final_transcripts.append(transcript.strip())
        logger.info("Deepgram final segment: %s", transcript.strip()[:80])

    async def _on_deepgram_utterance_end(self):
        """Called when Deepgram detects end of utterance (silence).

        Always set pending_turn if we have transcripts, regardless of state.
        The turn_watcher in plivo_stream.py will wait for processing_lock
        which ensures we don't process during greeting playback.
        """
        if self._final_transcripts:
            logger.info("Deepgram utterance end: %d segments pending", len(self._final_transcripts))
            self._pending_turn.set()

    # ------------------------------------------------------------------
    # Public properties
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

    @property
    def has_pending_turn(self) -> bool:
        return self._pending_turn.is_set()

    async def wait_for_turn(self, timeout: float = 60.0) -> bool:
        """Wait for Deepgram to signal a turn is ready. Returns False on timeout."""
        try:
            await asyncio.wait_for(self._pending_turn.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ------------------------------------------------------------------
    # Supervisor interaction
    # ------------------------------------------------------------------

    def inject_supervisor_hint(self, message: str):
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

    def finish_speaking(self):
        """Mark TTS playback as complete. Reset for next turn.

        Does NOT clear _final_transcripts -- user may have spoken during
        TTS playback (captured by Deepgram). Those transcripts should be
        processed in the next turn.
        """
        self._state = SpeakingState.LISTENING
        self._barge_in_event.clear()
        self._post_tts_guard = True
        self._tts_finished_at = time.monotonic()
        # Reset batch fallback state
        self.audio_buffer.clear()
        self._silence_vad_frames = 0
        self._cooldown_remaining = 2400
        self._speech_started = False
        self._speech_onset_count = 0
        self._vad.reset()

    def reset_listening(self):
        """Lightweight reset after barge-in or null turn.

        Does NOT clear _pending_turn -- that's only cleared in process_turn()
        after transcripts are consumed. Clearing here would lose barge-in speech.
        """
        self._state = SpeakingState.LISTENING
        self._barge_in_event.clear()
        self._silence_vad_frames = 0
        self._speech_started = len(self.audio_buffer) > 0
        self._speech_onset_count = 0

    # ------------------------------------------------------------------
    # Audio input
    # ------------------------------------------------------------------

    async def add_audio(self, mulaw_chunk: bytes) -> bool:
        """Add audio chunk. Returns True if speech pause detected.

        When Deepgram streaming is active:
        - Forwards all audio to Deepgram (continuous)
        - Barge-in handled by Deepgram interim transcripts (MinWords)
        - Turn detection handled by Deepgram utterance_end event
        - Returns True when _pending_turn is set

        When batch STT fallback (Marathi, no Deepgram):
        - Uses VAD-based silence detection (old path)
        """
        # Always forward to Deepgram if connected
        if self._deepgram:
            await self._deepgram.send_audio(mulaw_chunk)

            # During SPEAKING, audio still streams to Deepgram for barge-in.
            # MinWords check happens in _on_deepgram_interim callback.
            if self._state == SpeakingState.SPEAKING:
                return False

            # During BARGE_IN, wait for Deepgram utterance_end
            if self._state == SpeakingState.BARGE_IN:
                return self._pending_turn.is_set()

            # LISTENING: Deepgram handles endpointing via utterance_end callback
            return self._pending_turn.is_set()

        # --- Batch STT fallback (Marathi or no Deepgram key) ---
        return self._add_audio_batch_fallback(mulaw_chunk)

    def _add_audio_batch_fallback(self, mulaw_chunk: bytes) -> bool:
        """VAD-based speech pause detection for batch STT fallback."""
        vad_result = self._vad.process_chunk(mulaw_chunk)

        if self._state == SpeakingState.SPEAKING:
            return False

        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= len(mulaw_chunk)
            return False

        if not self._speech_started:
            if vad_result.is_speech:
                self._speech_onset_count += 1
                if self._speech_onset_count >= self._vad.config.min_speech_chunks:
                    self._speech_started = True
                    self.audio_buffer.extend(mulaw_chunk)
            else:
                self._speech_onset_count = 0
            return False

        self.audio_buffer.extend(mulaw_chunk)
        if not vad_result.is_speech:
            self._silence_vad_frames += 1
        else:
            self._silence_vad_frames = 0

        if len(self.audio_buffer) >= self._max_buffer_bytes:
            return True

        min_speech_bytes = int(self._vad.config.min_speech_ms / 1000 * 8000)
        return (len(self.audio_buffer) > min_speech_bytes
                and self._silence_vad_frames >= self._vad.config.min_silence_chunks)

    def flush_buffer(self):
        self.audio_buffer.clear()
        self._silence_vad_frames = 0

    # ------------------------------------------------------------------
    # Turn processing
    # ------------------------------------------------------------------

    async def process_turn(self, db_session=None, on_audio=None) -> bytes | None:
        """Process a turn: get transcript -> LLM -> TTS.

        When Deepgram is active, transcript comes from _final_transcripts.
        When batch fallback, transcript comes from audio_buffer -> STT.

        Returns b"" if audio was streamed, bytes for batch TTS, None for no response.
        """
        # Get transcript
        if self._use_streaming_stt and self._final_transcripts:
            transcript = " ".join(self._final_transcripts)
            self._final_transcripts.clear()
            self._pending_turn.clear()
        else:
            # Batch STT fallback
            transcript = await self._batch_transcribe()
            if not transcript:
                return None

        if not transcript.strip():
            self.reset_listening()
            return None

        # --- Hallucination / echo guards (still useful for both paths) ---
        words_raw = transcript.strip().lower().replace(",", " ").replace(".", " ").split()

        # Single-word hallucination guard
        _valid_single_words = {
            "hello", "hi", "hey", "yes", "no", "yeah", "nah", "help",
            "thanks", "bye", "okay", "ok", "please", "stop", "wait",
            "नमस्ते", "हां", "नहीं", "हेलो", "धन्यवाद",
        }
        if len(words_raw) == 1 and words_raw[0].rstrip(".,!?") not in _valid_single_words:
            logger.info("Hallucination guard: discarding single-word '%s'", transcript.strip())
            self.reset_listening()
            return None

        # Repetitive hallucination guard
        if len(words_raw) > 4:
            from collections import Counter
            word_counts = Counter(words_raw)
            most_common_word, most_common_count = word_counts.most_common(1)[0]
            if most_common_count / len(words_raw) > 0.6:
                logger.info("Hallucination guard: discarding repetitive '%s'", most_common_word)
                self.reset_listening()
                return None

        # Echo guard
        if self._post_tts_guard:
            echo_age = time.monotonic() - self._tts_finished_at
            if echo_age > 3.0:
                self._post_tts_guard = False
            else:
                self._post_tts_guard = False
                cleaned = transcript.strip().lower().rstrip(".!,")
                words = cleaned.split()
                if len(words) <= 4 and cleaned in self._echo_phrases:
                    logger.info("Echo guard: discarding '%s' (%.1fs after TTS)", transcript.strip(), echo_age)
                    self.reset_listening()
                    return None
                echo_words = {"yes", "yeah", "ya", "ok", "okay", "hmm", "hm", "uh", "um", "ah", "mm",
                              "right", "sure", "हो", "हां", "हम्म", "अच्छा"}
                if all(w.rstrip(".,!?") in echo_words for w in words):
                    logger.info("Echo guard: discarding all-echo '%s'", transcript.strip()[:80])
                    self.reset_listening()
                    return None

        # --- Process the turn ---
        self.start_speaking()
        logger.info("Turn %d - Customer: %s", self.turn_count, transcript)

        if db_session and self.conv_id:
            source = "deepgram_streaming" if self._use_streaming_stt else "batch_stt"
            await self._save_message(db_session, "customer", transcript, {"source": source, "turn": self.turn_count})

        try:
            # --- Streaming LLM + sentence-pipeline TTS ---
            if on_audio:
                try:
                    return await self._stream_llm_tts(transcript, db_session, on_audio)
                except Exception:
                    logger.exception("Streaming pipeline failed, falling back to batch")

            # --- Batch fallback ---
            return await self._batch_llm_tts(transcript, db_session)

        except httpx.HTTPStatusError as exc:
            logger.error("API error in turn %d (HTTP %d): %s",
                         self.turn_count, exc.response.status_code, exc.response.text[:200])
            self._state = SpeakingState.LISTENING
            return None
        except Exception:
            logger.exception("Error in voice AI turn %d", self.turn_count)
            self._state = SpeakingState.LISTENING
            return None

    async def _batch_transcribe(self) -> str | None:
        """Batch STT from audio buffer (Marathi fallback)."""
        min_speech_bytes = int(self._vad.config.min_speech_ms / 1000 * 8000)
        if len(self.audio_buffer) < min_speech_bytes:
            self.audio_buffer.clear()
            self._silence_vad_frames = 0
            return None

        audio_data = bytes(self.audio_buffer)
        self.audio_buffer.clear()
        self._silence_vad_frames = 0

        # Trim trailing silence
        trim_chunk = 160
        while len(audio_data) > trim_chunk:
            tail_pcm = audioop.ulaw2lin(audio_data[-trim_chunk:], 2)
            if audioop.rms(tail_pcm, 2) >= 400:
                break
            audio_data = audio_data[:-trim_chunk]
        if len(audio_data) < min_speech_bytes:
            return None

        wav_data = _mulaw_to_wav(audio_data)
        transcript = await sarvam.transcribe(wav_data, language=self.language)
        return transcript.strip() if transcript else None

    async def _stream_llm_tts(self, transcript: str, db_session, on_audio) -> bytes:
        """Streaming LLM -> sentence-pipelined TTS."""
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
                        await on_audio(_wav_to_mulaw(tts_audio))
                    except Exception:
                        logger.exception("Batch TTS also failed")

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

        return b""  # signal: audio streamed

    async def _batch_llm_tts(self, transcript: str, db_session) -> bytes:
        """Batch LLM -> batch TTS fallback."""
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

        tts_text = ai_response.text
        if len(tts_text) > 300:
            cut = tts_text[:300].rfind(".")
            tts_text = tts_text[:cut + 1] if cut > 100 else tts_text[:300]

        tts_audio = await sarvam.synthesize(tts_text, self.language, self.speaker)
        return _wav_to_mulaw(tts_audio)

    # ------------------------------------------------------------------
    # Greeting
    # ------------------------------------------------------------------

    async def stream_greeting(self, on_audio) -> None:
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
                await on_audio(_wav_to_mulaw(tts_audio))
            except Exception:
                logger.exception("Greeting TTS completely failed")

    async def get_greeting_audio(self) -> bytes | None:
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
            return _wav_to_mulaw(tts_audio)
        except Exception:
            logger.exception("Greeting TTS failed")
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
