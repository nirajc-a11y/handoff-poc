# Voice AI Flow Guide — Complete Audio Architecture

## Two Voice Modes

The system supports two completely different voice AI architectures, controlled by the `USE_LIVEKIT_AGENT` env var (`app/config.py:32`).

| | Legacy VoiceAISession | LiveKit Agent Mode |
|---|---|---|
| **Flag** | `use_livekit_agent=False` | `use_livekit_agent=True` |
| **Processing** | All in-process (single FastAPI worker) | Distributed (separate agent worker process) |
| **STT** | Deepgram WebSocket (mulaw 8kHz direct) | Deepgram via LiveKit plugin (PCM 24kHz) |
| **LLM** | Groq via ai_engine | Groq via SarvamLLM plugin |
| **TTS** | Sarvam streaming HTTP | Deepgram TTS via LiveKit plugin |
| **Entry point** | `plivo_stream.py:135-419` | `plivo_stream.py:131 -> _handle_livekit_bridge()` |
| **Key files** | `voice_agent.py`, `deepgram_stt.py`, `sarvam.py` | `plivo_livekit_bridge.py`, `livekit_agent.py`, `sarvam_llm_plugin.py` |

---

## Mode 1: Legacy VoiceAISession

### Audio Flow Diagram

```
Plivo Cloud (SIP/PSTN)
    |
    | WebSocket: /api/v1/plivo/audio-stream
    | mulaw 8kHz, 160 bytes per 20ms frame
    v
plivo_stream.py:385-396 (WebSocket event loop)
    |
    | base64 decode -> raw mulaw bytes
    | session.add_audio(audio_bytes)
    v
voice_agent.py:272-335 (VoiceAISession.add_audio)
    |
    |--- If streaming STT enabled (Deepgram):
    |      |
    |      | deepgram_stt.send_audio(mulaw_chunk)
    |      | -> Deepgram WS receives mulaw 8kHz natively (no conversion!)
    |      |
    |      | Deepgram callbacks:
    |      |   on_interim(transcript) -> barge-in detection
    |      |   on_final(transcript)   -> accumulated in _final_transcripts
    |      |   on_utterance_end()     -> sets _pending_turn event
    |      v
    |   _turn_watcher task (plivo_stream.py:330-341)
    |      | waits for session._pending_turn
    |      | triggers process_and_respond()
    |
    |--- If batch STT (Marathi fallback):
    |      | Silero VAD detects speech onset/offset
    |      | audio_buffer accumulates raw mulaw
    |      | On silence timeout -> batch transcription
    |
    v
voice_agent.py:350-439 (process_turn)
    |
    | 1. Collect final transcripts
    | 2. Call ai_engine (Groq LLM) for response
    | 3. Stream LLM response -> sentence-level TTS
    |
    |--- Streaming path (on_audio callback):
    |      | _stream_llm_tts() -> sentences streamed from Groq
    |      | Each sentence -> sarvam.synthesize_stream()
    |      | -> yields mulaw chunks (already 8kHz mulaw from Sarvam)
    |      | -> on_audio(chunk) callback
    |      | -> send_chunk_with_bargein() in plivo_stream.py
    |      | -> ws.send_json({"event": "playAudio", ...})
    |      | -> Plivo plays audio to caller
    |
    |--- Batch fallback:
    |      | _batch_llm_tts() -> full LLM response
    |      | sarvam.synthesize() -> WAV bytes
    |      | _wav_to_mulaw() -> mulaw 8kHz
    |      | returned as single blob
    |      | send_audio() in plivo_stream.py chunks it
    v
Plivo Cloud -> Caller hears response
```

### Key Audio Formats (Legacy)

| Stage | Format | Sample Rate | Notes |
|-------|--------|-------------|-------|
| Plivo -> Backend | mulaw | 8kHz | Raw telephony format |
| Backend -> Deepgram STT | mulaw | 8kHz | No conversion needed! |
| Sarvam TTS streaming | mulaw | 8kHz | Returns mulaw directly |
| Sarvam TTS batch | WAV PCM | 8kHz | Converted to mulaw via `_wav_to_mulaw()` |
| Backend -> Plivo | mulaw | 8kHz | base64 encoded in JSON |

### Greeting Flow (Legacy)

```
voice_agent.py:564-604 (stream_greeting)
    |
    |--- Check in-memory cache (sarvam.get_cached_greeting)
    |    Key: "{text[:50]}|{language}|{speaker}"
    |    HIT -> play cached chunks immediately (0ms)
    |
    |--- MISS: Call sarvam.synthesize_stream(greeting_text)
    |    -> yields mulaw chunks
    |    -> on_audio(chunk) sends each to Plivo
    |    -> Cache chunks for next time (sarvam.cache_greeting)
    |
    |--- Timeout (5s): Fall back to batch synthesis (3s timeout)
    |--- Both fail: Caller hears silence
```

### Barge-In Detection (Legacy)

```
voice_agent.py:286-335

During TTS playback (state=SPEAKING):
  -> Deepgram interim transcripts arrive
  -> count_real_words() filters backchannels ("uh", "yeah", etc.)
  -> If >=2 real words detected -> _barge_in_event.set()
  -> TTS sending loop checks barge_in_event and stops
  -> clearAudio sent to Plivo (cancel current playback)
  -> State -> LISTENING
```

---

## Mode 2: LiveKit Agent Mode

### Audio Flow Diagram

```
Plivo Cloud (SIP/PSTN)
    |
    | WebSocket: /api/v1/plivo/audio-stream
    | mulaw 8kHz, 160 bytes per 20ms frame
    v
plivo_stream.py:421-492 (_handle_livekit_bridge)
    |
    | base64 decode -> raw mulaw bytes
    | bridge.feed_audio(mulaw_bytes)
    v
plivo_livekit_bridge.py:262-286 (feed_audio)
    |
    | mulaw 8kHz -> PCM 16-bit 8kHz (audioop.ulaw2lin)
    | PCM 8kHz -> PCM 24kHz (audioop.ratecv, upsample 3x)
    | Buffer PCM, emit 20ms frames (960 bytes = 480 samples @ 24kHz)
    | -> audio_source.capture_frame(AudioFrame)
    | -> Published as "caller-audio" track in LiveKit room
    v
LiveKit Cloud Room (WebRTC mesh)
    |
    | Room: "room-{conversation_id}"
    | Participants:
    |   - "plivo-bridge" (publishes caller audio, subscribes to agent audio)
    |   - "agent-{job_id}" (subscribes to caller audio, publishes responses)
    |
    v
livekit_agent.py:1036-1110 (entrypoint)
    |
    | Agent auto-joins room via LiveKit Agents SDK
    | Receives caller audio as PCM track
    |
    | Pipeline: AgentSession(vad, stt, llm, tts)
    |   - VAD: Silero (pre-loaded in prewarm)
    |   - STT: Deepgram Nova-2 (streaming WebSocket)
    |   - LLM: SarvamLLM plugin (wraps Groq)
    |   - TTS: Deepgram Aura (streaming WebSocket)
    |
    | Agent publishes TTS audio as audio track in LiveKit room
    v
LiveKit Cloud Room
    |
    | *** TWO PATHS FOR AGENT AUDIO TO REACH CALLER ***
    |
    |--- Path A: LiveKit Native Routing (WebRTC mesh)
    |    | LiveKit automatically routes agent's audio track
    |    | to plivo-bridge participant via WebRTC
    |    | Bridge receives it as a subscribed track
    |    | THIS IS HOW THE CALLER ACTUALLY HEARS AUDIO
    |
    |--- Path B: Explicit Bridge Forwarding (BROKEN)
    |    | plivo_livekit_bridge.py:288-364 (_forward_agent_audio)
    |    | rtc.AudioStream(track, sample_rate=8000) -> PCM frames
    |    | RMS silence check: if rms < threshold -> SKIP
    |    | *** ALL FRAMES SKIPPED (0 chunks sent) ***
    |    | PCM -> mulaw (audioop.lin2ulaw)
    |    | -> ws.send_json({"event": "playAudio", ...})
    |    | -> Plivo -> Caller
    v
Plivo Cloud -> Caller hears response
```

### The "0 Chunks" Mystery — EXPLAINED

**Observation:** Bridge logs "Agent audio forwarding ended: 0 chunks sent to Plivo" but caller hears AI responses perfectly.

**Root Cause:** There are TWO audio paths from agent to caller:

1. **LiveKit Native Path (works):** When the agent publishes audio to the LiveKit room, LiveKit's WebRTC mesh delivers it to ALL participants including `plivo-bridge`. The bridge's `rtc.Room` connection receives this audio natively through WebRTC, which then flows back to Plivo through the room's underlying WebRTC transport.

2. **Explicit Forwarding Path (broken):** The bridge's `_forward_agent_audio()` method subscribes to the agent's audio track via `rtc.AudioStream` and tries to convert PCM -> mulaw -> Plivo. But the RMS silence check (`rms < 50`) filters out ALL frames, resulting in 0 chunks sent.

**Why Path B fails:** The `rtc.AudioStream(track, sample_rate=8000)` resamples from 24kHz to 8kHz. The resampled PCM frames likely have very low amplitude (possibly due to the resampler's output being quieter than expected at 8kHz), causing all frames to fall below the silence threshold of 50 RMS.

**Why Path A works anyway:** LiveKit's built-in participant audio routing doesn't go through the bridge's explicit forwarding code. It routes audio at the WebRTC transport layer, bypassing the RMS filter entirely.

**Impact:** The explicit forwarding path (`_forward_agent_audio`) is currently dead code — it runs but produces no output. The caller hears audio purely through LiveKit's native routing. This means:
- The silence threshold filtering is unnecessary for LiveKit mode
- The mulaw conversion in `_forward_agent_audio` never executes
- The `playAudio` messages to Plivo from this path are never sent

**Fix Options:**
1. **Remove the RMS filter** — Let all frames through since we want agent audio to reach the caller
2. **Lower the threshold** — Set `bridge_silence_threshold=10` or lower
3. **Remove Path B entirely** — If LiveKit native routing works reliably, the explicit forwarding is redundant
4. **Add diagnostic logging** — Log RMS values of first N frames to understand the actual amplitude

### Key Audio Formats (LiveKit)

| Stage | Format | Sample Rate | Notes |
|-------|--------|-------------|-------|
| Plivo -> Bridge | mulaw | 8kHz | Raw telephony |
| Bridge -> LiveKit | PCM 16-bit | 24kHz | Upsampled 3x via audioop.ratecv |
| LiveKit -> Deepgram STT | PCM 16-bit | 24kHz | Via agent's audio track subscription |
| Deepgram TTS -> LiveKit | PCM 16-bit | 24kHz | Published as agent audio track |
| LiveKit -> Bridge (native) | WebRTC | varies | Automatic room routing |
| LiveKit -> Bridge (explicit) | PCM 16-bit | 8kHz | Downsampled via rtc.AudioStream (BROKEN) |
| Bridge -> Plivo | mulaw | 8kHz | Only greeting reaches Plivo this way |

### Greeting Flow (LiveKit)

```
plivo_livekit_bridge.py:189-260 (stream_greeting)
    |
    |--- Check Redis greeting cache
    |    Key: "greeting:{tenant_id}:{language}:{content_hash}"
    |    HIT -> _send_mulaw_to_plivo(cached_bytes) -> 0ms TTS wait!
    |
    |--- MISS: Call sarvam.synthesize_stream(greeting_text)
    |    -> yields mulaw chunks
    |    -> Send each chunk to Plivo via playAudio
    |    -> Cache full audio to Redis (background, non-blocking)
    |
    | NOTE: Greeting is sent DIRECTLY to Plivo via playAudio,
    | NOT through the LiveKit room. This bypasses the agent entirely
    | and ensures the caller hears something immediately while
    | the agent is still joining the room.
```

### Pre-Warming Flow (LiveKit)

```
plivo.py:plivo_answer() (when call is answered, IVR starts)
    |
    | Background task _prewarm_pipeline():
    |   1. room_prewarmer.prewarm(conv_id, tenant_id, language, company)
    |      -> Creates LiveKit room via API
    |      -> Room triggers agent worker dispatch automatically
    |      -> Takes ~3s but runs during IVR (~16s of caller navigation)
    |
    |   2. warm_greeting_cache(tenant_id, language, company, speaker)
    |      -> Checks Redis cache
    |      -> HIT: skip (already cached from previous call)
    |      -> MISS: Synthesize via Sarvam, store in Redis (TTL 24h)
    |
    | Both run concurrently via asyncio.gather()
    | By the time DTMF arrives (~16s later), both are ready

plivo.py:plivo_dtmf() -> _handle_ai_handoff()
    |
    | Returns Plivo XML: <Stream bidirectional>
    | Plivo opens WebSocket to /audio-stream

plivo_stream.py:_handle_livekit_bridge()
    |
    | bridge = PlivoLiveKitBridge(...)
    | bridge.start()
    |   -> room_prewarmer.consume(conv_id) -> PrewarmedRoom found!
    |   -> Skip room creation (already done!)
    |   -> Connect to existing room as "plivo-bridge"
    |   -> Agent already in room (dispatched during pre-warm)
    |   -> Agent audio track subscribed immediately
    |
    | bridge.stream_greeting()
    |   -> Redis cache HIT -> Play cached greeting instantly
    |
    | Result: ~680ms from DTMF to greeting (vs 4.5s without pre-warming)
```

---

## Supervisor Features

Both modes support real-time call supervision:

### Legacy Mode

| Feature | Endpoint | How |
|---------|----------|-----|
| Listen | `WS /supervisor/listen/{conv_id}` | Copies audio from session_registry to supervisor WebSocket |
| Whisper | `POST /supervisor/whisper/{conv_id}` | Injects system message into conversation_history |
| Barge | `POST /supervisor/barge/{conv_id}` | Sets `_barge_in_event`, sends `clearAudio`, redirects to conference |

### LiveKit Mode

| Feature | Endpoint | How |
|---------|----------|-----|
| Listen | `POST /supervisor/livekit-token/{conv_id}` | Returns LiveKit room token (listen-only) |
| Whisper | `POST /supervisor/livekit-whisper/{conv_id}` | Sends data channel message to agent |
| Barge | `POST /supervisor/livekit-barge/{conv_id}` | Sends barge signal, mutes agent, returns publish token |

---

## Common Patterns

### State Machine Integration

Both modes follow the same state machine:
```
INITIATED -> RINGING -> IVR -> AI_HANDLING -> WRAP_UP -> ENDED
```

The voice AI session runs during `AI_HANDLING`. Transitions to `WRAP_UP` happen on:
- Customer hangup (Plivo call-status webhook)
- AI-initiated end (customer says goodbye)
- Escalation to human (AI confidence drop)

### Error Handling

| Error | Legacy | LiveKit |
|-------|--------|---------|
| STT connection drop | Deepgram reconnect (1 retry) | Agent handles internally |
| TTS timeout | 5s streaming timeout + 3s batch fallback | Deepgram WebSocket (faster, less likely) |
| LLM error | httpx-specific catches + batch fallback | SarvamLLM plugin handles |
| Bridge disconnect | N/A | `self._running = False`, clean shutdown |
| Full pipeline failure | Silence (caller waits) | Silence (caller waits) |

### Session Registry

Both modes register in `session_registry` (module-level dict) keyed by `conversation_id`:
- Legacy: `SessionHandle(session=VoiceAISession, plivo_ws=ws)`
- LiveKit: Registered in `_handle_livekit_bridge` (supervisor access)

---

## File Reference

| File | Purpose | Mode |
|------|---------|------|
| `app/api/v1/plivo_stream.py` | WebSocket handler, routes to correct mode | Both |
| `app/voice_ai/voice_agent.py` | VoiceAISession: STT+LLM+TTS in-process | Legacy |
| `app/voice_ai/deepgram_stt.py` | Streaming STT WebSocket client | Legacy |
| `app/voice_ai/sarvam.py` | Sarvam STT/TTS HTTP client + greeting cache | Legacy (+shared) |
| `app/voice_ai/vad.py` | Silero VAD for speech detection | Legacy |
| `app/voice_ai/plivo_livekit_bridge.py` | Plivo <-> LiveKit audio bridge | LiveKit |
| `app/voice_ai/livekit_agent.py` | LiveKit Agent worker (STT+LLM+TTS) | LiveKit |
| `app/voice_ai/sarvam_llm_plugin.py` | Groq/Sarvam LLM wrapper for LiveKit | LiveKit |
| `app/voice_ai/sarvam_tts_plugin.py` | Sarvam TTS wrapper for LiveKit | LiveKit |
| `app/voice_ai/session_registry.py` | Active session tracking for supervisor | Both |
| `app/services/greeting_cache.py` | Redis-backed greeting TTS cache | LiveKit |
| `app/services/room_prewarmer.py` | Pre-creates LiveKit rooms during IVR | LiveKit |
| `app/api/v1/plivo.py` | Plivo webhooks (answer, dtmf, status) | Both |
| `app/api/v1/supervisor.py` | Supervisor listen/whisper/barge | Both |
