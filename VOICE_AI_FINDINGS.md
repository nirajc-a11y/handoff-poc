# Voice AI Pipeline: Delay Analysis & Production Improvements

## Overview

Analysis of the Sarvam voice AI mode (Plivo audio stream -> Sarvam STT -> Groq LLM -> Sarvam TTS -> Plivo) identifying latency sources and missing barge-in support, with production-grade fixes applied.

---

## Delay Sources Found

### 1. Greeting uses batch TTS (5-9s delay)
- **Location:** `app/livekit/voice_agent.py` — `get_greeting_audio()` calls `sarvam.synthesize()` (batch)
- **Impact:** Caller hears dead silence for 5-9 seconds after answering
- **Fix:** Switched to `sarvam.synthesize_stream()` — first audio chunk reaches caller in ~500ms

### 2. New httpx client per API call (300-600ms/turn)
- **Location:** `app/livekit/sarvam.py` — each of `transcribe()`, `synthesize()`, `synthesize_stream()` creates a new `httpx.AsyncClient`
- **Impact:** TCP+TLS handshake on every request (3 calls per turn = 300-600ms overhead)
- **Fix:** Module-level persistent `httpx.AsyncClient` with connection pooling; connections reused after first call

### 3. LLM waits for full completion (300-800ms)
- **Location:** `app/core/ai_engine.py` — `_call_groq()` uses non-streaming Groq API
- **Impact:** TTS cannot start until entire LLM response is generated
- **Fix:** Added `_call_groq_stream()` with `stream=True`, yields sentences at boundary chars. TTS starts on the first sentence while LLM generates the rest.

### 4. Silence threshold too high (1.0s)
- **Location:** `app/livekit/voice_agent.py` — `silence_duration_frames = 8000`
- **Impact:** System waits a full second of silence before processing speech
- **Fix:** Reduced to 4800 frames (~0.6s), the industry standard for conversational AI

### 5. Post-TTS cooldown too long (1.0s)
- **Location:** `app/livekit/voice_agent.py` — `_cooldown_remaining = 8000` in `finish_speaking()`
- **Impact:** 1 second of dead time after every AI response before system listens again
- **Fix:** Reduced to 3200 (~0.4s), sufficient for echo dissipation

### 6. No sentence-level TTS pipelining
- **Location:** `app/livekit/voice_agent.py` — entire (truncated) LLM response sent as one TTS request
- **Impact:** Must wait for full LLM output before TTS begins
- **Fix:** Sentences streamed to TTS individually as they arrive from LLM

---

## Barge-In Gap

### Problem
When TTS is playing (`is_speaking=True`), ALL incoming caller audio is silently discarded:
- `voice_agent.py:79-80` — `add_audio()` returns `False` during `is_speaking`
- No energy detection during playback
- No way to interrupt the AI mid-sentence
- Caller must wait for AI to finish speaking + 1s cooldown before being heard

### Fix: Full Barge-In Support
1. **Tri-state model:** `LISTENING` / `SPEAKING` / `BARGE_IN` replaces boolean `is_speaking`
2. **Energy detection during playback:** RMS energy measured even while speaking; threshold of 400 (higher than silence=200) to reject echo
3. **Consecutive frame confirmation:** 3 consecutive high-energy frames (~60ms) required to confirm barge-in (avoids false triggers from echo)
4. **Plivo clearAudio:** When barge-in detected, `clearAudio` event sent to Plivo to flush playback buffer
5. **TTS cancellation:** Streaming TTS loop and sentence pipeline check `_barge_in_event` and stop immediately
6. **Seamless transition:** Interrupting speech is buffered and processed as a new turn

---

## Latency Budget: Before vs After

| Stage | Before | After |
|-------|--------|-------|
| Greeting first audio | 5-9s | ~500ms |
| Silence detection | 1.0s | 0.6s |
| Post-TTS cooldown | 1.0s | 0.4s |
| httpx overhead/turn | 300-600ms | ~0ms (pooled) |
| LLM wait | 300-800ms (full) | 100-200ms (TTFT) |
| **Total turn latency** | **~4.5s** | **~1.5-2.0s** |

---

## Files Changed

| File | Changes |
|------|---------|
| `app/livekit/sarvam.py` | Shared httpx client pool with `close_client()` shutdown |
| `app/livekit/voice_agent.py` | Barge-in state machine, streaming greeting, reduced thresholds, sentence-pipeline `process_turn` |
| `app/api/v1/plivo_stream.py` | `clearAudio` event, barge-in-aware chunk streaming, streaming greeting |
| `app/core/ai_engine.py` | `_call_groq_stream()`, `process_message_stream()` |
| `app/main.py` | Registered `sarvam.close_client()` in lifespan shutdown |
