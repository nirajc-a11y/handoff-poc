# Call Flow Analysis — LiveKit + Plivo + Sarvam Pipeline

**Call ID:** `ed7bd71b-66fd-4174-b1f8-c419608afad5`
**Provider Call ID:** `35b01bab-0ba4-422f-ab2a-b5e0f0b2c33a`
**Tenant:** `dc03d12f-23d9-46b4-8ff7-12095c3fae7f`
**Date:** 2026-04-03, 14:23-14:25 IST
**Total Call Duration:** ~74s (14:23:43 -> 14:24:57)

---

# Part 1: Latency Analysis (from logs)

## Phase 1: Call Initiation (14:23:43.132)

| Timestamp | Event | Delta |
|-----------|-------|-------|
| 14:23:43.132 | Plivo outbound call initiated (+918031140170 -> +919422571198) | T=0 |
| 14:23:43.142 | Call service logged initiation | +10ms |
| 14:23:43.204 | Handoff engine: `initiated -> ringing` | +72ms |

**Phase latency: 72ms** (call setup to state transition)

## Phase 2: Ringing -> Answer (14:23:43 -> 14:23:49)

| Timestamp | Event | Delta from call start |
|-----------|-------|-----------------------|
| 14:23:49.890 | Call answered, Handoff engine: `ringing -> ivr` | +6.76s |
| 14:23:49.979 | Call recording started | +6.85s |

**Ring duration: ~6.7s** (network + callee pickup time -- external, not controllable)

## Phase 3: IVR Menu (14:23:49 -> 14:24:12)

| Timestamp | Event | Delta from answer |
|-----------|-------|-------------------|
| 14:23:49.890 | IVR started (DTMF menu served) | T=0 |
| 14:24:12.105 | DTMF received, Handoff engine: `ivr -> ai_handling` | +22.2s |
| 14:24:12.112 | AI handoff config: voice_mode=sarvam, lang=en, speaker=ritu | +22.2s |

**IVR duration: ~22.2s** (caller navigating menu -- user-dependent)

## Phase 4: AI Pipeline Startup (14:24:12 -> 14:24:15)

This is the critical infrastructure warm-up phase after DTMF triggers AI handoff.

| Timestamp | Event | Delta from AI trigger |
|-----------|-------|-----------------------|
| 14:24:12.105 | `ivr -> ai_handling` transition | T=0 |
| 14:24:12.157 | Plivo audio WebSocket connected | +52ms |
| 14:24:14.899 | LiveKit received job request | +2.79s |
| 14:24:14.916 | LiveKit signal client connecting to WSS | +2.81s |
| 14:24:14.956 | LiveKit job runner initializing (tid=29536) | +2.85s |
| 14:24:15.167 | Job runner initialized | +3.06s |
| 14:24:15.437 | LiveKit agent joining room | +3.33s |
| 14:24:15.453 | Input stream attached | +3.35s |
| 14:24:15.467 | Adaptive interruption detector initialized | +3.36s |
| 14:24:15.489 | HTTP session created | +3.38s |
| 14:24:15.496 | **LiveKit agent fully started** | +3.39s |
| 14:24:15.577 | PlivoLiveKitBridge started | +3.47s |
| 14:24:15.578 | Bridge stream started | +3.47s |

**AI pipeline startup: ~3.47s**

Breakdown:
- Plivo WS connect: 52ms
- **LiveKit job dispatch + agent spawn: ~2.74s** (12.157 -> 14.899) -- LARGEST DELAY
- LiveKit room join + session setup: ~600ms (14.899 -> 15.496)
- Bridge startup: ~80ms

## Phase 5: Greeting TTS (14:24:15 -> 14:24:18)

| Timestamp | Event | Delta from bridge start |
|-----------|-------|-----------------------|
| 14:24:15.581 | Greeting TTS requested (Sarvam) | T=0 |
| 14:24:15.672 | LiveKit started reading plivo-bridge stream | +91ms |
| 14:24:16.236 | Subscribed to agent audio track | +655ms |
| 14:24:16.661 | Sarvam TTS HTTP 200 received | +1.08s |
| 14:24:16.769 | Deepgram TTS WebSocket established | +1.19s |
| 14:24:16.985 | Deepgram STT WebSocket established | +1.40s |
| 14:24:18.942 | Sarvam TTS stream complete (47,300 bytes) | +3.36s |

**Greeting TTS total: ~3.36s** (request to full audio delivered)

- Sarvam TTS first response: ~1.08s
- Sarvam TTS streaming duration: ~2.28s (audio content delivery)

**Caller hears greeting at:** ~14:24:16.6 (first audio chunks) = **~4.5s after AI handoff trigger**

## Phase 6: First Conversational Turn (14:24:18 -> 14:24:31)

| Timestamp | Event | Delta |
|-----------|-------|-------|
| 14:24:30.329 | User transcript received: "Can you help me with the company name?" | -- |
| 14:24:30.329 | Transcript delay (STT pipeline): **408ms** | reported by LiveKit |
| 14:24:30.474 | Preemptive generation started | +145ms from transcript |
| 14:24:30.946 | AEC warmup: interruptions disabled for 3s | +617ms |
| 14:24:31.473 | **First agent audio chunk sent to Plivo** (320 bytes) | +1.14s from transcript |
| 14:24:33.947 | AEC warmup expired, interruptions re-enabled | +3.62s from transcript |

**Turn latency (user speech end -> first audio to caller): ~1.14s** -- Good

Breakdown:
- STT transcript delay: 408ms
- Preemptive generation lead: 145ms
- LLM + TTS to first audio chunk: ~1.0s (from preemptive gen start)

## Phase 7: Call Termination (14:24:56 -> 14:25:01)

| Timestamp | Event | Delta |
|-----------|-------|-------|
| 14:24:56.720 | Recording status received (duration=66s) | -- |
| 14:24:57.526 | Plivo call status: completed (customer hangup) | +806ms |
| 14:24:57.569 | `end_call` failed: call not found (already ended) | +43ms |
| 14:24:57.593 | `ai_handling -> wrap_up` | +67ms |
| 14:24:57.626 | `wrap_up -> ended` (auto-disposition) | +33ms |
| 14:24:57.661 | Recording downloaded from Plivo (133,488 bytes) | +35ms |
| 14:24:59.197 | Plivo stream disconnected | +1.57s |
| 14:24:59.241 | LiveKit agent session closing (participant disconnect) | +1.62s |
| 14:24:59.252 | LiveKit room disconnected (ClientInitiated) | +1.63s |
| 14:24:59.254 | PlivoLiveKitBridge stopped (70 chunks sent total) | +1.63s |
| 14:25:01.285 | Session fully closed | +3.74s |
| 14:25:02.849 | Worker shutdown initiated | +5.33s |

**Teardown latency: ~5.3s** (call end -> full cleanup)

Note: `end_call` error is benign -- Plivo already terminated the call before our hangup request arrived.

## Latency Summary

| Metric | Value | Assessment |
|--------|-------|------------|
| Call setup (initiate -> ringing state) | 72ms | Excellent |
| Ring time (ringing -> answer) | 6.7s | External (callee) |
| IVR navigation | 22.2s | User-dependent |
| **AI pipeline startup** | **3.47s** | High -- LiveKit job dispatch is 2.74s |
| Greeting TTS (Sarvam, full stream) | 3.36s | Acceptable but adds to wait |
| **Time from AI trigger to caller hears greeting** | **~4.5s** | Noticeable delay |
| STT transcript delay | 408ms | Good |
| **First-turn response latency** | **~1.14s** | Good |
| Preemptive generation lead time | 145ms | Good |
| AEC warmup hold | 3.0s | Safety mechanism |
| Call teardown | 5.3s | Acceptable (background) |

## Bottleneck Analysis

### 1. LiveKit Job Dispatch -- 2.74s
The gap between Plivo WS connecting (14:24:12.157) and LiveKit receiving the job (14:24:14.899) is the single largest controllable delay. This includes:
- LiveKit cloud dispatching the job to the registered worker
- Worker accepting and spawning a new process (tid=29536)

**Potential mitigations:**
- Pre-warm LiveKit agents (keep idle agents in rooms)
- Use LiveKit's `dispatch` API with lower latency region routing
- Investigate if the 2.74s includes network round-trip to LiveKit cloud (India South region)

### 2. Greeting Delivery -- 4.5s total from AI trigger
Caller waits ~4.5s in silence after pressing DTMF before hearing the AI greeting. This is the sum of pipeline startup (3.47s) + Sarvam TTS first chunk (~1s).

**Potential mitigations:**
- Play a "Please wait" filler audio from Plivo XML while pipeline spins up
- Pre-generate and cache common greetings
- Start LiveKit room creation earlier (during IVR, before DTMF result)

### 3. Sarvam TTS Streaming -- 3.36s for greeting
The full greeting audio takes 3.36s to stream. First chunks arrive at ~1.08s.

**Potential mitigations:**
- Shorter greeting text
- Switch to Deepgram TTS for greeting (WebSocket already established at 14:24:16.769)
- Pre-synthesize static greetings

## Timeline Diagram

```
14:23:43  --- CALL INITIATED -----------------------------------------
              | 72ms
14:23:43  --- RINGING ------------------------------------------------
              | 6.7s (external ring time)
14:23:49  --- ANSWERED -> IVR ----------------------------------------
              | 22.2s (caller navigates DTMF menu)
14:24:12  --- DTMF -> AI HANDLING ------------------------------------
              | 52ms   Plivo audio WS connected
              | 2.74s  LiveKit job dispatch wait
              | 600ms  LiveKit room join + agent setup
              | 80ms   Plivo<->LiveKit bridge started
14:24:15  --- AI PIPELINE READY --------------------------------------
              | 1.08s  Sarvam TTS first response
              | 2.28s  TTS audio streaming
14:24:18  --- GREETING COMPLETE --------------------------------------
              | ~11.4s (conversation -- user speaking/listening)
14:24:30  --- USER SPEECH DETECTED -----------------------------------
              | 408ms  STT transcript delay
              | 145ms  preemptive generation
              | ~590ms LLM + TTS pipeline
14:24:31  --- FIRST RESPONSE AUDIO -> PLIVO --------------------------
              | ~26s   (continued conversation)
14:24:57  --- CUSTOMER HANGUP ----------------------------------------
              | 67ms   ai_handling -> wrap_up
              | 33ms   wrap_up -> ended
              | 1.6s   stream + bridge cleanup
              | 3.7s   full session teardown
14:25:01  --- SESSION CLOSED -----------------------------------------
```

---

# Part 2: Complete Code Flow (file:line references)

## Phase 1: Outbound Call Initiation

```
POST /api/v1/calls/outbound
  -> app/api/v1/calls.py — initiate_outbound_call()
    -> app/services/call_service.py — creates Conversation (state=INITIATED) + ChannelSession
    -> app/core/handoff_engine.py — process_trigger(DIAL)
       -> state_machine.transition(INITIATED, DIAL) -> (RINGING, state_change)
       -> Acquires row-level lock (SELECT FOR UPDATE)
       -> Persists HandoffEvent audit record
       -> Publishes "conversation.state_changed" to Redis
    -> app/providers/plivo/telephony.py — initiate_call()
       -> asyncio.to_thread(plivo_client.calls.create(...))
       -> Sets answer_url = /api/v1/plivo/answer?tenant_id=...
       -> Sets hangup_url, status_callback, fallback_url
```

## Phase 2: Call Answered -> IVR

```
Plivo webhook -> POST /api/v1/plivo/answer
  -> app/api/v1/plivo.py:196 — plivo_answer()
    -> _find_or_create_conversation() [plivo.py:129-158]
       -> Lookup by CallUUID (provider_session_id) first
       -> Fallback: find most recent active conversation by phone number
       -> If none: create new Conversation + ChannelSession
    -> handoff_engine.process_trigger(ANSWER) [handoff_engine.py]
       -> transition(RINGING, ANSWER) -> (IVR, state_change)
    -> Returns Plivo XML Response:
       <GetDigits action="/api/v1/plivo/dtmf?tenant_id=...&conv_id=...&menu_id=...">
         <Speak>Welcome message with menu options</Speak>
       </GetDigits>
    -> Fire-and-forget: asyncio.create_task(_start_call_recording()) [plivo.py:299]
```

## Phase 3: DTMF -> AI Handoff

```
Plivo webhook -> POST /api/v1/plivo/dtmf
  -> app/api/v1/plivo.py:311 — plivo_dtmf()
    -> app/core/ivr_engine.py — process_dtmf(menu_id, digit)
       -> Looks up IVRMenuOption by menu_id + digit
       -> Returns action_type: "ai_handoff" | "human_queue" | "submenu" | "play_message" | "hangup"
    -> If action_type == "ai_handoff":
       -> handoff_engine.process_trigger(DTMF_AI) -> (AI_HANDLING, ivr_to_ai)
       -> Reads tenant voice config: language, speaker, voice_mode
       -> Returns Plivo XML:
          <Stream bidirectional keepCallAlive
            url="wss://.../api/v1/plivo/audio-stream?tenant_id=...&conv_id=...&language=en&speaker=ritu">
          </Stream>
```

## Phase 4: Audio Stream -> LiveKit Bridge

```
Plivo opens WebSocket -> /api/v1/plivo/audio-stream
  -> app/api/v1/plivo_stream.py:117 — plivo_audio_stream(ws)
    -> Checks settings.use_livekit_agent && settings.livekit_url [line 131]
    -> Calls _handle_livekit_bridge() [line 132]

_handle_livekit_bridge() [plivo_stream.py:420]:
  1. Fetches tenant name from DB [line 437-444]
  2. Creates PlivoLiveKitBridge(conv_id, tenant_id, language, plivo_ws_send=ws.send_json) [line 446]
  3. bridge.start() [plivo_livekit_bridge.py:90]:
     a. Creates LiveKit room via REST API [line 99-109]
        -> lk_api.LiveKitAPI.room.create_room(name="room-{conv_id}", metadata={...})
        -> Room metadata includes: tenant_id, conversation_id, language, company_name
     b. Generates JWT access token for "plivo-bridge" participant [line 117-131]
        -> Grants: room_join, can_publish, can_subscribe
     c. Connects to LiveKit room [line 149]
        -> rtc.Room().connect(livekit_url, jwt_token)
     d. Creates AudioSource (24kHz mono) [line 153]
        -> Publishes as LOCAL_AUDIO_TRACK with source=SOURCE_MICROPHONE [line 155-156]
        -> This is how the LiveKit Agent sees caller audio
     e. Registers track_subscribed handler [line 137-147]
        -> When agent publishes audio track, starts _forward_agent_audio() task
  4. Enters WebSocket event loop [line 457]:
     - "start" event [line 467-473]:
       -> Extracts streamId from start_data
       -> bridge.update_stream_sid(stream_sid)
       -> asyncio.create_task(bridge.stream_greeting())
     - "media" event [line 475-479]:
       -> base64.b64decode(payload) -> raw mulaw bytes
       -> bridge.feed_audio(mulaw_bytes)
     - "stop" event [line 481-483]:
       -> break
  5. finally: bridge.stop() [line 490]
```

## Phase 5: LiveKit Agent Joins

```
LiveKit Cloud auto-dispatches job to registered worker
  -> app/voice_ai/livekit_agent.py

Worker startup:
  -> prewarm(proc) [line 35-37]:
     -> Loads Silero VAD model into proc.userdata["vad"]

Job entrypoint:
  -> entrypoint(ctx: JobContext) [line 40]:
    a. ctx.connect(auto_subscribe=AUDIO_ONLY) [line 42]
    b. Parses room metadata (JSON) [line 44-55]:
       -> language, company_name, tenant_id, conversation_id
    c. Creates component stack:
       - VAD: silero (from prewarm or fresh load) [line 65]
       - LLM: SarvamLLM(language, company_name) [line 68]
              -> app/voice_ai/sarvam_llm_plugin.py
              -> Wraps app/core/ai_engine.py (Groq/Sarvam streaming)
              -> Maintains bounded conversation history (20 messages)
              -> Detects escalation/end-call flags
       - TTS: deepgram.TTS(model="aura-2-andromeda-en") [line 71-74]
              *** BUG: Always English regardless of language param ***
       - STT: deepgram.STT(model="nova-2", language=mapped) [line 77-81]
              -> Language mapped: en->en-US, hi->hi, mr->mr
    d. Creates Agent with instructions [line 84-90]
    e. Registers data_received handler [line 93-105]:
       -> "whisper" messages: injects system hint into LLM
       -> "barge" messages: logged but NOT IMPLEMENTED
    f. Creates AgentSession and starts [line 108-115]:
       -> session.start(agent, room=ctx.room)
       -> Greeting already played by bridge -- agent just listens
```

## Phase 6: Bidirectional Audio Flow

```
CALLER -> PLIVO -> BRIDGE -> LIVEKIT AGENT:

  Plivo sends "media" event with base64 mulaw
    -> plivo_stream.py:475-479 — base64 decode
    -> bridge.feed_audio(mulaw_bytes) [plivo_livekit_bridge.py:194]:
       1. mulaw 8kHz -> PCM 16-bit 8kHz [audioop.ulaw2lin, line 203]
       2. Upsample 8kHz -> 24kHz [audioop.ratecv, line 205]
       3. Buffer to _pcm_buffer [line 208]
       4. Emit complete frames (960 bytes = 20ms @ 24kHz 16-bit mono) [line 209-219]
          -> rtc.AudioFrame(data, sample_rate=24000, num_channels=1, samples_per_channel=480)
          -> audio_source.capture_frame(frame)
       5. Frame published as MICROPHONE track to LiveKit room
       6. LiveKit Agent's STT receives it as user audio input

LIVEKIT AGENT -> BRIDGE -> PLIVO -> CALLER:

  Agent publishes audio track (STT->LLM->TTS pipeline output)
    -> track_subscribed handler fires [plivo_livekit_bridge.py:137-147]
    -> Creates AudioStream(track, sample_rate=8000, num_channels=1) [line 142-144]
    -> Spawns _forward_agent_audio(audio_stream) task [line 145-146]

  _forward_agent_audio() [plivo_livekit_bridge.py:221]:
    for each audio event from agent stream:
      1. Extract PCM data from frame [line 236]
      2. RMS silence check (threshold=50) [line 242-244]
         -> Skip silence frames to avoid flooding Plivo
      3. PCM 8kHz 16-bit -> mulaw [audioop.lin2ulaw, line 247]
      4. Buffer to _mulaw_out_buffer [line 248]
      5. Send 320-byte chunks (40ms @ 8kHz mulaw) to Plivo [line 251-268]:
         -> ws.send_json({ event: "playAudio", streamId, media: { payload: base64(chunk) } })
    6. Flush remaining buffer on stream end [line 272-286]
```

## Phase 7: Greeting (Parallel Path -- Doesn't Wait for Agent)

```
bridge.stream_greeting() [plivo_livekit_bridge.py:161]:
  1. Guard: check _stream_sid is set [line 164-166]
  2. Construct greeting text based on language [line 168-171]:
     -> "en": "Hello! Welcome to {company_name}. I'm Maya, your AI assistant..."
     -> "mr": Marathi equivalent
  3. Call Sarvam TTS streaming [line 175-190]:
     -> app/voice_ai/sarvam.py — synthesize_stream(text, language, speaker)
        -> POST https://api.sarvam.ai/text-to-speech/stream
        -> Yields mulaw chunks as HTTP response streams
     -> For each chunk:
        -> ws.send_json({ event: "playAudio", streamId, media: { payload: base64(chunk) } })
  4. Runs concurrently with LiveKit agent startup
     -> Caller hears greeting while agent is still joining room
```

## Phase 8: Conversation Turn (LiveKit AgentSession pipeline)

```
LiveKit AgentSession internal pipeline (managed by livekit-agents SDK):

  Caller audio (from bridge's MICROPHONE track)
    -> Silero VAD (voice activity detection, endpointing)
       -> Determines when user starts/stops speaking
    -> Deepgram STT (streaming transcription via WebSocket)
       -> Converts speech to text in real-time
       -> Reported transcript delay: ~408ms
    -> SarvamLLM [app/voice_ai/sarvam_llm_plugin.py]:
       -> chat() method called with conversation history
       -> Builds messages array (bounded to 20 entries) [sarvam_llm_plugin.py:128]
       -> Injects any supervisor hints as system messages
       -> Calls app/core/ai_engine.py — process_message_stream()
          -> Streams sentences from Groq/Sarvam LLM
       -> Detects escalation flags (should_escalate)
       -> Detects end-call flags (should_end_call)
    -> Deepgram TTS (aura-2-andromeda-en model)
       -> Converts LLM text response to audio
       -> Low-latency streaming via WebSocket
    -> Audio published to room
       -> bridge._forward_agent_audio() picks it up
       -> PCM -> mulaw -> Plivo -> caller's phone
```

## Phase 9: Call Termination

```
CUSTOMER HANGS UP:

  Path A: Plivo WebSocket "stop" event [plivo_stream.py:481-483]:
    -> break from event loop
    -> finally: bridge.stop() [plivo_livekit_bridge.py:299]:
       1. _running = False [line 301]
       2. Cancel _subscribe_task [line 302-303]
       3. room.disconnect() [line 305]
       4. Clear audio_source [line 307]

  Path B: Plivo call-status webhook [plivo.py:893]:
    -> POST /api/v1/plivo/call-status
    -> Finds ChannelSession by CallUUID
    -> Updates session.status = "completed"
    -> Attempts provider.end_call() (may fail if already ended -- benign)
    -> handoff_engine.process_trigger(CUSTOMER_DISCONNECT)
       -> transition(AI_HANDLING, CUSTOMER_DISCONNECT) -> (WRAP_UP, state_change)
    -> handoff_engine.process_trigger(DISPOSITION_SUBMITTED)
       -> transition(WRAP_UP, DISPOSITION_SUBMITTED) -> (ENDED, state_change)
    -> Auto-sets disposition to "call_completed"

  Path C: Plivo recording-status webhook [plivo.py]:
    -> POST /api/v1/plivo/recording-status
    -> Downloads MP3 from Plivo media URL (e.g. aps1.media.plivo.com/...)
    -> Saves to recordings/{conv_id}_full_{timestamp}.mp3
    -> Creates/updates Message record with recording file path

  LiveKit cleanup (triggered by bridge disconnect):
    -> Room participant "plivo-bridge" disconnects
    -> LiveKit Agent detects participant disconnect [livekit-agents SDK]
    -> AgentSession closes automatically (close_on_disconnect=True by default)
    -> Worker reports session to LiveKit Cloud
```

## Phase 10: Event Broadcasting (Real-time Dashboard Updates)

```
Each state transition in handoff_engine:
  -> event_bus.publish(Event(...)) [app/core/events.py:57-63]
     -> Event(topic="conversation.state_changed", tenant_id, payload={conv_id, ...})
     -> Serializes to JSON
     -> Redis PUBLISH to channel named by topic

  -> app/ws/broadcaster.py — WSBroadcaster._subscribe_loop() [line 38-66]:
     -> pubsub.psubscribe("conversation.*", "agent.*", "queue.*", "campaign.*", "channel.*")
     -> Receives pmessage from Redis
     -> Event.from_json(message["data"])
     -> ws_manager.broadcast_to_tenant(tenant_id, {...})

  -> app/ws/manager.py — WSConnectionManager [line 15-30]:
     -> Finds all WebSocket connections for tenant_id
     -> Sends JSON to each: { type, event_id, timestamp, data }
     -> Removes dead connections on send failure

  -> Frontend: use-websocket.ts
     -> WebSocket at ws://host/api/v1/ws/dashboard?tenant_id=...
     -> "conversation.message_added" -> appends to React Query cache or invalidates
     -> "conversation.*" -> invalidates conversation list queries
     -> "agent.status_changed" -> invalidates agent list queries
     -> "queue.stats_updated" -> sets stats directly in cache
```

---

# Part 3: Issues Catalog

## CRITICAL -- Must Fix Before Production

### C1: TTS Language Hardcoded to English
- **File:** `app/voice_ai/livekit_agent.py:71-74`
- **Code:** `tts_plugin = deepgram.TTS(model="aura-2-andromeda-en")`
- **Impact:** Marathi/Hindi callers hear English TTS responses. The `language` param is correctly parsed from room metadata but never used for TTS model selection.
- **Fix:** Map language to Deepgram model: `{"en": "aura-2-andromeda-en", "hi": "aura-2-andromeda-hi"}`. For languages without Deepgram support (e.g. Marathi), fall back to Sarvam TTS plugin.

### C2: No Max Call Duration
- **Files:** `livekit_agent.py`, `plivo_livekit_bridge.py`, `plivo_stream.py`
- **Impact:** A call can run indefinitely -- consuming a LiveKit room, bridge resources, and a Plivo WebSocket connection. No watchdog timer exists anywhere.
- **Fix:** Add `asyncio.wait_for()` around the main WebSocket loop in `_handle_livekit_bridge()` with `settings.max_call_duration_seconds` (default 3600). Log and clean up on timeout.

### C3: LiveKit Room Creation Failure Silently Ignored
- **File:** `app/voice_ai/plivo_livekit_bridge.py:110-112`
- **Code:** `except Exception: logger.debug("Room may already exist, continuing")`
- **Impact:** If room creation fails for a real reason (auth error, network issue, quota exceeded), the bridge continues and connects to a room that doesn't exist. The agent never joins, caller hears silence.
- **Fix:** After the create attempt, verify the room exists via `room_api.room.list_rooms()` or catch only the specific "already exists" error code.

### C4: No Timeout on bridge.start()
- **File:** `app/voice_ai/plivo_livekit_bridge.py:149`
- **Code:** `await self._room.connect(settings.livekit_url, jwt_token)` -- no timeout
- **Impact:** If LiveKit cloud is unreachable, this hangs forever. The Plivo WebSocket stays open, caller hears silence with no error feedback.
- **Fix:** Wrap in `asyncio.wait_for(self._room.connect(...), timeout=settings.livekit_connect_timeout)`.

### C5: Unbounded Audio Buffers
- **File:** `app/voice_ai/plivo_livekit_bridge.py:81-82`
- **Code:** `self._pcm_buffer = bytearray()` and `self._mulaw_out_buffer = bytearray()`
- **Impact:** If audio consumption is slower than production (agent audio backpressure, network stall), buffers grow without limit. On a 1-hour call with stuck audio, this could consume hundreds of MB.
- **Fix:** Cap both buffers at `settings.max_audio_buffer_bytes` (default 64KB). When exceeded, log a warning and drain oldest data.

### C6: Supervisor Barge Not Implemented in LiveKit Path
- **File:** `app/voice_ai/livekit_agent.py:104-105`
- **Code:** `elif msg_type == "barge": logger.info("Supervisor barge received...")`
- **Impact:** Supervisor clicks "Barge" but nothing happens. The message is acknowledged in logs but no action is taken -- agent keeps talking, call is not redirected.
- **Fix:** On barge message, cancel the agent session and publish a data message to the bridge signaling it should redirect the Plivo call to the escalation endpoint.

### C7: No Session Registry for LiveKit Path
- **File:** `app/api/v1/plivo_stream.py:420-490`
- **Impact:** The legacy path registers sessions in `session_registry` (line 159-160) for supervisor listen/whisper/barge. The LiveKit path skips this entirely. Supervisor endpoints (`/api/v1/supervisor/listen/{conv_id}`, etc.) can't find LiveKit sessions.
- **Fix:** Register the bridge in `session_registry` with a LiveKit-specific `SessionHandle` that routes supervisor operations through LiveKit data channels.

### C8: Greeting Race Condition with stream_sid
- **File:** `app/api/v1/plivo_stream.py:473`
- **Code:** `asyncio.create_task(bridge.stream_greeting())` -- fired on "start" event
- **But:** `bridge.stream_greeting()` checks `self._stream_sid` (line 164) which was *just* set on the previous line (470). The task is created after `update_stream_sid()`, but `stream_greeting` is an async function that calls `synthesize_stream()` which takes ~1s before first chunk. The real risk: if a second "start" event arrives (Plivo reconnect), stream_sid updates mid-greeting.
- **Fix:** Pass stream_sid explicitly to `stream_greeting()` or snapshot it at call time.

### C9: Redis Connection Not Validated at Startup
- **Files:** `app/core/redis.py:16-26`, `app/main.py`
- **Code:** `get_redis()` is lazy -- pool created on first use, no connectivity test.
- **Impact:** If Redis URL is wrong or Redis is down, the app starts successfully. First real-time event (state transition) discovers Redis is unreachable, logs an error, and silently drops the event. Dashboard never updates.
- **Fix:** Add `await get_redis().ping()` in lifespan startup. Fail fast if Redis is unreachable.

## HIGH -- Should Fix Before Production

### H1: No Health Check Endpoint
- **File:** `app/main.py`
- **Impact:** No way to monitor if the app is alive and connected to PostgreSQL, Redis, and LiveKit. Kubernetes/ECS cannot detect degraded state.
- **Fix:** Add `GET /health` that checks DB connectivity (`SELECT 1`), Redis (`PING`), and optionally LiveKit API reachability.

### H2: 60s Plivo Stream Timeout
- **Files:** `app/api/v1/plivo_stream.py:352,459`
- **Code:** `await asyncio.wait_for(ws.receive_text(), timeout=60.0)`
- **Impact:** If there's a 60s silence gap (caller on hold, agent typing), the stream drops and the call breaks. Plivo sends media events continuously even during silence, but network issues could delay them.
- **Fix:** Increase to `settings.plivo_stream_timeout_seconds` (default 120s).

### H3: No Reconnection Logic for Redis
- **Files:** `app/core/redis.py`, `app/core/events.py`
- **Impact:** If Redis connection drops mid-operation, all event publishing fails permanently. The `redis-py` async client has built-in retry for some operations, but the pubsub subscriber in `broadcaster.py` will exit its loop.
- **Fix:** Add `retry_on_error=[ConnectionError, TimeoutError]` to Redis client config. Wrap broadcaster subscribe loop in a retry-with-backoff outer loop.

### H4: Fire-and-Forget Call Recording
- **File:** `app/api/v1/plivo.py:299`
- **Code:** `asyncio.create_task(_start_call_recording(...))`
- **Impact:** Recording may silently fail (Plivo API error, auth issue). No retry, no notification. Compliance risk if recordings are required.
- **Fix:** Track the task, log failure prominently, and optionally retry once with backoff.

### H5: WebSocket Endpoint Has No Heartbeat
- **File:** `app/api/v1/ws.py`
- **Impact:** Dead WebSocket connections (client crash, network drop) are not detected until the next broadcast attempt. Stale connections accumulate in `ws_manager`.
- **Fix:** Add periodic ping in the WS endpoint (every `settings.ws_heartbeat_interval_seconds`, default 30s). Remove connections that don't respond.

### H6: No Request Tracing / Correlation ID
- **Files:** All API handlers, handoff_engine, event_bus
- **Impact:** Cannot trace a single call across Plivo webhooks, bridge operations, LiveKit agent, and event bus. Production debugging is extremely difficult.
- **Fix:** Generate a correlation ID at call initiation, propagate through all log messages and events. Add `correlation_id` field to Event dataclass.

### H7: Sarvam TTS Streaming Has No Timeout
- **File:** `app/voice_ai/plivo_livekit_bridge.py:175`
- **Code:** `async for mulaw_chunk in synthesize_stream(...)` -- no timeout
- **Impact:** If Sarvam API hangs (network issue, rate limit), greeting never plays. Caller waits in silence indefinitely.
- **Fix:** Wrap in `asyncio.wait_for(..., timeout=settings.sarvam_tts_timeout_seconds)`.

### H8: No Circuit Breaker for External APIs
- **Files:** `app/voice_ai/sarvam.py`, `app/core/ai_engine.py`
- **Impact:** If Sarvam/Groq/Deepgram is down, every single call attempt fails immediately with the same error. No backoff, no fallback, no "fail open" strategy.
- **Fix:** Implement a simple circuit breaker: after N consecutive failures, short-circuit for M seconds before retrying. Consider fallback paths (e.g., Groq TTS if Sarvam is down).

### H9: Bridge Doesn't Detect Agent Join Timeout
- **File:** `app/voice_ai/plivo_livekit_bridge.py`
- **Impact:** If the LiveKit agent worker is down or overloaded, the agent never joins the room. The bridge sits idle after greeting -- caller says something but gets no response. No error detection or escalation.
- **Fix:** After `start()`, start a watchdog timer. If `_subscribe_task` is not created within `settings.livekit_agent_join_timeout_seconds`, log error and either retry or escalate to human.

### H10: Audio Send Failures Silently Return
- **File:** `app/voice_ai/plivo_livekit_bridge.py:267-269`
- **Code:** `except Exception: logger.warning(...); return`
- **Impact:** If Plivo WS dies mid-conversation, agent audio forwarding quietly stops. No cleanup triggered, bridge stays "running".
- **Fix:** Set `_running = False` on send failure to trigger full cleanup cascade.

## MEDIUM -- Should Fix for Robustness

### M1: Hardcoded Values Scattered Across Codebase
- **Locations:**
  - Silence RMS threshold: 50 (`plivo_livekit_bridge.py:229`)
  - Mulaw chunk size: 320 (`plivo_livekit_bridge.py:228`)
  - Echo buffer: 0.5s (`plivo_stream.py:170`)
  - Process turn timeout: 15s (`plivo_stream.py:274`)
  - Plivo stream timeout: 60s (`plivo_stream.py:352,459`)
  - Conversation history limit: 20 (`sarvam_llm_plugin.py:128`)
  - Max audio buffer: 40KB (`voice_agent.py:130`)
- **Fix:** Move all to `app/config.py` as named settings.

### M2: No Metrics / Observability
- **Impact:** Cannot measure STT/LLM/TTS latencies, turn counts, error rates, buffer sizes, or call quality in production. Flying blind.
- **Fix:** Add structured logging for key metrics. Consider OpenTelemetry spans for the audio pipeline.

### M3: Conversation Lookup Fallback by Phone Number
- **File:** `app/api/v1/plivo.py:129-158`
- **Impact:** If CallUUID doesn't match (rare), code falls back to finding "most recent active conversation" by phone number. Two concurrent calls from/to the same number would collide.
- **Fix:** Remove fallback or add explicit guards against concurrent calls to same number.

### M4: Agent Assignment Race Condition
- **File:** `app/core/routing_engine.py:69-94`
- **Impact:** `find_available_agent()` selects agent, then `assign_agent()` updates in a separate step. Two simultaneous queue assignments could pick the same agent, exceeding `max_concurrent` conversations.
- **Fix:** Use `SELECT ... FOR UPDATE` on AgentStatus row before incrementing `current_conversations`.

### M5: Event Bus is Fire-and-Forget
- **Files:** `app/core/events.py`, `app/ws/broadcaster.py`
- **Impact:** Redis Pub/Sub loses messages if no subscriber is listening. If broadcaster restarts, events during the gap are permanently lost. Dashboard may show stale state.
- **Fix:** For critical state changes, consider Redis Streams (persistent, replayable) instead of Pub/Sub. Or add a "full refresh" mechanism to the frontend on reconnect.

### M6: No WebSocket Connection Limits Per Tenant
- **File:** `app/ws/manager.py`
- **Impact:** A single tenant could open thousands of WebSocket connections (malicious or buggy frontend), exhausting server resources.
- **Fix:** Add `max_connections_per_tenant` config. Reject new connections when limit is reached.

### M7: Global Logging Filter Suppresses LiveKit Errors
- **File:** `app/voice_ai/plivo_livekit_bridge.py:27-38`
- **Code:** Filters any log message containing "ignoring" + "lk.agent.session" or "lk.transcription"
- **Impact:** Legitimate LiveKit errors that happen to mention these strings are silently dropped from logs.
- **Fix:** Make filters more specific -- match exact message patterns, not substrings. Or move to per-logger filters instead of root logger.

### M8: bridge.stop() Doesn't Await subscribe_task
- **File:** `app/voice_ai/plivo_livekit_bridge.py:302-303`
- **Code:** `self._subscribe_task.cancel()` but no `await`
- **Impact:** Task cancellation is fire-and-forget. If the task is mid-send when cancelled, the Plivo WS send may raise an exception that's never caught.
- **Fix:** `await` the task after cancelling: `try: await self._subscribe_task except CancelledError: pass`

### M9: Inbound Channel Session Provider Hardcoded to "mock"
- **File:** `app/services/call_service.py:146`
- **Impact:** Inbound calls always get `provider="mock"` in their ChannelSession record, regardless of actual provider (Plivo/Twilio). Breaks provider-specific operations later.
- **Fix:** Read provider from tenant config JSONB or pass from webhook handler.

### M10: Side-Effect Exceptions Swallowed in HandoffEngine
- **File:** `app/core/handoff_engine.py:480-484, 504-507, 525-529`
- **Code:** `except Exception: logger.exception(...)` -- then continues
- **Impact:** Hold/unhold/wrap-up state transitions succeed in the database, but the actual provider operation (Plivo API call) fails silently. Call state and provider state diverge.
- **Fix:** Either fail the entire transition (rollback) or mark the conversation with a `sub_state` flag indicating provider operation failed, for manual intervention.

## LOW -- Nice to Have

### L1: No Graceful Shutdown for Active Calls
- **File:** `app/main.py` lifespan shutdown
- **Impact:** On SIGTERM, `broadcaster.stop()` and `engine.dispose()` run immediately. Active bridges get `stop()` called in their finally blocks, but there's no coordinated drain period.
- **Fix:** Track active sessions in a global set. On shutdown, signal all sessions to wrap up, wait up to N seconds, then force-close.

### L2: Docker Compose Has No Health Checks
- **File:** `docker-compose.yaml`
- **Impact:** `docker compose up` reports all services as "running" even if PostgreSQL is still initializing or Redis failed to start. Dependent services may fail on first connection.
- **Fix:** Add health check configs for postgres (`pg_isready`), redis (`redis-cli ping`), and app (`curl /health`).

### L3: Redis max_connections Hardcoded to 20
- **File:** `app/core/redis.py:23`
- **Fix:** Use `settings.redis_max_connections`.

### L4: VAD Model Load at Startup Can Hang
- **File:** `app/main.py:62`
- **Code:** `_get_model_path()` -- downloads ONNX model if not cached, no timeout or try/except
- **Impact:** If the model CDN is unreachable, app startup hangs indefinitely.
- **Fix:** Wrap in try/except with timeout. Log warning and continue (VAD will load on first call instead).

### L5: No Dependency Pinning
- **File:** `pyproject.toml`
- **Impact:** All dependencies use `>=` constraints. A new release of any dependency could break the build.
- **Fix:** Generate a `requirements.lock` or use `pnpm` lockfile equivalent for Python (e.g., `uv lock`).
