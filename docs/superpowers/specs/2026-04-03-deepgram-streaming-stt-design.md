# Deepgram Streaming STT + MinWords Barge-in

## Problem

The current batch STT architecture has three issues that can't be fixed with threshold tuning:

1. **Text cropping** -- Audio accumulated during cooldown/echo guard is lost. "Tell me about the company" becomes "me about the company".
2. **No reliable barge-in** -- Plivo media streams have no AEC. TTS echo registers as speech on both energy and VAD detectors. Any audio-only barge-in approach produces false positives.
3. **Slow turn processing** -- Accumulate audio -> batch STT -> LLM -> TTS adds latency at every step.

## Solution

Replace batch STT with a persistent Deepgram WebSocket per call session. Audio streams to Deepgram continuously. Interim transcripts enable MinWords barge-in. Final transcripts trigger LLM processing.

## Architecture

```
Plivo audio stream (mulaw 8kHz, 20ms chunks)
    │
    ├──► Deepgram WebSocket (continuous, full-duplex)
    │       encoding=mulaw, sample_rate=8000
    │       ├── Interim transcripts → barge-in word counting
    │       └── Final transcripts → LLM input queue
    │
    ├──► Silero VAD (speech onset detection only)
    │       Used to gate when we START paying attention to
    │       Deepgram transcripts (avoid processing silence)
    │
    └──► Audio buffer (removed for normal path, kept for fallback)

On final transcript received:
    transcript text → Groq LLM (streaming) → Sarvam TTS (streaming) → Plivo
```

## New File: `app/voice_ai/deepgram_stt.py`

Manages a persistent WebSocket connection to Deepgram per call session.

```python
class DeepgramStreamingSTT:
    """Per-session streaming STT via Deepgram WebSocket."""

    def __init__(self, language: str = "en", on_interim, on_final, on_utterance_end):
        # Opens wss://api.deepgram.com/v1/listen
        # Params: encoding=mulaw, sample_rate=8000, model=nova-3,
        #         interim_results=true, utterance_end_ms=1000,
        #         endpointing=300, language=<lang>, vad_events=true

    async def connect(self):
        """Open WebSocket, start receive loop in background task."""

    async def send_audio(self, mulaw_chunk: bytes):
        """Send raw mulaw audio to Deepgram. Called for every Plivo chunk."""

    async def close(self):
        """Send CloseStream message, close WebSocket."""
```

**Callbacks:**
- `on_interim(transcript: str, words: list)` -- Fired on every interim result. Used for barge-in word counting.
- `on_final(transcript: str)` -- Fired when Deepgram finalizes a segment. Accumulated for LLM input.
- `on_utterance_end()` -- Fired when Deepgram detects end of utterance (silence). Triggers turn processing.

**Deepgram WebSocket params:**
- `encoding=mulaw` -- Native mulaw support, zero conversion
- `sample_rate=8000` -- Matches Plivo telephony
- `model=nova-3` -- Best accuracy for English telephony
- `interim_results=true` -- Real-time partial transcripts for barge-in
- `utterance_end_ms=1000` -- Silence duration to signal utterance end
- `endpointing=300` -- Minimum silence before considering endpoint (ms)
- `smart_format=true` -- Auto-punctuation and formatting
- `language=en` -- Per-session language (en/hi for Deepgram, fall back to Sarvam batch for mr)

## MinWords Barge-in Strategy

During SPEAKING state, Deepgram still receives audio (including echo). The key insight: **echo transcribes as silence or short backchannels, real speech transcribes as real words**.

```python
BACKCHANNELS = {"uh", "um", "mm", "hmm", "yeah", "yes", "ok", "okay", "right", "sure",
                "uh-huh", "mhm", "ah"}

def check_barge_in(interim_transcript: str) -> bool:
    words = interim_transcript.strip().split()
    real_words = [w for w in words if w.lower().rstrip(".,!?") not in BACKCHANNELS]
    return len(real_words) >= 3  # 3+ real words = confirmed interruption
```

When barge-in confirmed:
1. Set `_barge_in_event` (stops TTS streaming)
2. Send `clearAudio` to Plivo
3. Deepgram keeps running -- captures the rest of the interrupting speech
4. On next `utterance_end`, process the full transcript through LLM

## Changes to `voice_agent.py`

### `__init__` additions:
- `self._deepgram: DeepgramStreamingSTT` -- per-session instance
- `self._final_transcripts: list[str]` -- accumulates final segments
- `self._pending_turn: asyncio.Event` -- set when utterance_end fires
- Remove: batch audio buffer for STT (keep only for Sarvam fallback)

### `add_audio()` changes:
- Always forward chunk to `self._deepgram.send_audio(mulaw_chunk)`
- VAD still runs for speech onset detection (logging, metrics)
- SPEAKING state: no audio-based barge-in. Barge-in handled by `on_interim` callback.
- LISTENING state: no silence-based endpointing. Endpointing handled by Deepgram `on_utterance_end`.
- Return value `True` (speech pause) now set by Deepgram callback, not silence counting.

### `process_turn()` changes:
- No longer does STT (Deepgram already transcribed)
- Receives transcript from `self._final_transcripts`
- Still does: hallucination guard, echo guard, LLM call, TTS streaming

### Barge-in flow:
```
SPEAKING state:
    Plivo audio → Deepgram (continuous)
    Deepgram interim → on_interim callback
        → count real words (exclude backchannels)
        → if >= 3 real words: set _barge_in_event
    plivo_stream.py sees barge_in_requested → clearAudio
    State → LISTENING (via reset_listening or similar)
    Deepgram keeps receiving → captures rest of user speech
    Deepgram utterance_end → process full transcript
```

## Changes to `plivo_stream.py`

- On WebSocket connect: `await session.start_deepgram()`
- On WebSocket close: `await session.stop_deepgram()`
- Turn processing triggered by `session._pending_turn` event instead of `add_audio() -> True`
- The main audio loop becomes simpler: just forward chunks and check events

## Changes to `config.py`

```python
deepgram_api_key: str = ""
```

## Changes to `pyproject.toml`

```
"websockets>=12.0",  # For Deepgram WebSocket client
```

## Language Handling

| Language | Streaming STT | Batch STT Fallback |
|----------|--------------|-------------------|
| English | Deepgram Nova-3 (streaming) | Groq Whisper |
| Hindi | Deepgram Nova-3 (streaming, `language=hi`) | Sarvam saaras:v3 |
| Marathi | Sarvam saaras:v3 (batch, no streaming) | Groq Whisper |

Deepgram supports Hindi but not Marathi. For Marathi calls, fall back to the existing batch STT path (audio buffer + Sarvam).

## What Stays the Same

- Plivo transport layer (no LiveKit needed)
- Silero VAD (speech onset logging + Marathi fallback endpointing)
- Groq LLM (streaming sentences)
- Sarvam TTS (streaming mulaw)
- Echo guard and hallucination guards (text-level, still useful)
- All handoff/supervisor/state machine code
- Session registry, supervisor listen/whisper/barge

## Verification

1. `pip install -e .` with new websockets dependency
2. Start server, make test call
3. Verify in logs: "Deepgram connected", interim transcripts appearing in real-time
4. Speak while AI is talking -- verify barge-in triggers on 3+ words, not on echo
5. Verify full transcript captured (no cropping at start)
6. Verify Marathi falls back to batch STT gracefully
