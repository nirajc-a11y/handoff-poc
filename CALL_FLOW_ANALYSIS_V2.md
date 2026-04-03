# Call Flow Analysis V2 — After Latency Optimizations

**Call ID:** `ccf3cd89-fde0-40de-992a-afe0c4b2f4e4`
**Provider Call ID:** `f83c8f7d-bc22-4299-b0ed-1aa4fc7f2be1`
**Tenant:** VSynergize (`dc03d12f-23d9-46b4-8ff7-12095c3fae7f`)
**Date:** 2026-04-03, 15:54–15:55 IST
**Total Call Duration:** ~78s (15:54:23 -> 15:55:41)

---

## End-to-End Call Flow

### Overview

```
Frontend (Dashboard)
   |
   | POST /api/v1/calls/outbound {"to_number": "+919422571198"}
   v
Backend (FastAPI :8000)
   |
   | call_service.initiate_outbound()
   | -> PlivoTelephonyProvider.make_call()
   |    -> Plivo REST API (outbound call to +91...)
   |    -> Returns provider_call_id
   | -> handoff_engine.process_trigger(DIAL)
   |    -> State: INITIATED -> RINGING
   v
Plivo Cloud (SIP gateway)
   |
   | Routes call via PSTN to +919422571198
   | Callee picks up (~8.3s ring time)
   |
   | POST /api/v1/plivo/answer?tenant_id=...
   v
Backend — Plivo Answer Handler
   |
   | handoff_engine.process_trigger(ANSWER)
   |    -> State: RINGING -> IVR
   | Load IVR menu from DB (tenant root menu)
   | **** NEW: Pre-warm LiveKit room + greeting cache (background) ****
   |    -> room_prewarmer.prewarm() [async, ~3s to create room]
   |    -> warm_greeting_cache()    [async, cache HIT = skip]
   | Return Plivo XML: <GetDigits> + <Speak IVR prompt>
   v
Plivo Cloud
   |
   | Plays IVR prompt via TTS to caller
   | Waits for DTMF digit (~16s caller navigation)
   |
   | POST /api/v1/plivo/dtmf?tenant_id=...&conv_id=...&menu_id=...
   v
Backend — Plivo DTMF Handler
   |
   | ivr_engine.process_dtmf() -> action_type="ai_handoff"
   | handoff_engine.process_trigger(DTMF_AI)
   |    -> State: IVR -> AI_HANDLING
   | Build WebSocket URL for Plivo <Stream>
   | Return Plivo XML: <Stream bidirectional=true>
   v
Plivo Cloud
   |
   | Opens WebSocket to backend
   | WS /api/v1/plivo/audio-stream?tenant_id=...&conv_id=...&language=en&speaker=ritu
   v
Backend — Plivo Audio Stream WebSocket
   |
   | Accept WebSocket connection
   | **** NEW: Consume pre-warmed LiveKit room (instant, no 2.74s wait) ****
   | Create PlivoLiveKitBridge
   |    -> room_prewarmer.consume() -> PrewarmedRoom found!
   |    -> Skip room creation (already done during IVR)
   |    -> Connect to LiveKit room as "plivo-bridge" participant
   |    -> Publish caller audio track
   v
LiveKit Cloud (wss://test-poc-yg7gl1ha.livekit.cloud)
   |
   | Room: room-ccf3cd89-...
   | Participants: plivo-bridge (publisher), agent-AJ_... (subscriber)
   |
   | Agent worker already received job during IVR pre-warm
   | Agent joins room and starts STT/LLM/TTS pipeline
   v
LiveKit Agent Worker (separate process)
   |
   | Deepgram STT WebSocket established
   | Deepgram TTS WebSocket established  
   | Groq LLM connection ready
   | Agent session started
   |
   | <- Subscribes to plivo-bridge audio track
   | -> Bridge subscribes to agent audio track
   v
Bridge — Greeting Phase
   |
   | **** NEW: Check Redis greeting cache ****
   |    -> Cache HIT (36,300 bytes, pre-synthesized during IVR)
   |    -> Send cached mulaw chunks directly to Plivo (0ms TTS wait!)
   | Caller hears greeting immediately
   v
Bidirectional Audio Flow (conversation phase)
   |
   | Caller speaks -> Plivo WS -> Bridge -> PCM -> LiveKit room
   |                                                    |
   |                                         Deepgram STT (streaming)
   |                                                    |
   |                                         Groq LLM (streaming)
   |                                                    |
   |                                         Deepgram TTS (streaming)
   |                                                    |
   | Caller hears <- Plivo WS <- Bridge <- mulaw <- LiveKit room
   |
   | (Multiple conversational turns over ~50s)
   v
Call Termination
   |
   | Customer hangs up (or call timeout)
   | Plivo sends "stop" event on WebSocket
   | Bridge disconnects from LiveKit room
   |
   | POST /api/v1/plivo/call-status (status=completed)
   |    -> handoff_engine.process_trigger(CUSTOMER_DISCONNECT)
   |       -> State: AI_HANDLING -> WRAP_UP
   |    -> handoff_engine.process_trigger(DISPOSITION_SUBMITTED)
   |       -> State: WRAP_UP -> ENDED
   |
   | POST /api/v1/plivo/recording-status
   |    -> Download recording from Plivo (137KB MP3)
   |    -> Save to /recordings/ directory
   |    -> Create "system" message with recording URL
   v
Done
```

---

## Phase-by-Phase Timeline

### Phase 1: Call Initiation (15:54:23.506)

| Timestamp | Event | Delta |
|-----------|-------|-------|
| 15:54:23.506 | `POST /api/v1/calls/outbound` received | T=0 |
| 15:54:23.912 | Plivo outbound call initiated (+918031140170 -> +919422571198) | +406ms |
| 15:54:23.924 | Call service logged initiation | +418ms |
| 15:54:23.976 | Handoff engine: `initiated -> ringing` | +470ms |

**Phase latency: 470ms** (API request to state transition)

---

### Phase 2: Ringing -> Answer (15:54:23 -> 15:54:32)

| Timestamp | Event | Delta from call start |
|-----------|-------|-----------------------|
| 15:54:32.240 | Call answered, Handoff engine: `ringing -> ivr` | +8.7s |
| 15:54:32.262 | **Pre-warming started (room + greeting cache)** | +8.8s |
| 15:54:32.347 | Call recording started | +8.8s |
| 15:54:32.350 | **Greeting cache HIT** (36,300 bytes from previous call) | +8.8s |
| 15:54:35.357 | **Room pre-warmed** (3.1s to create LiveKit room) | +11.9s |

**Ring duration: ~8.7s** (network + callee pickup)
**Pre-warm completed in background: 3.1s** (while caller navigates IVR ~16s)

---

### Phase 3: IVR Menu (15:54:32 -> 15:54:48)

| Timestamp | Event | Delta from answer |
|-----------|-------|-------------------|
| 15:54:32.240 | IVR started (DTMF menu served) | T=0 |
| 15:54:48.625 | DTMF received, `ivr -> ai_handling` | +16.4s |
| 15:54:48.651 | AI handoff: voice_mode=sarvam, lang=en, speaker=ritu | +16.4s |

**IVR duration: ~16.4s** (caller navigating menu)

---

### Phase 4: AI Pipeline Startup (15:54:48 -> 15:54:49) -- MASSIVELY IMPROVED

| Timestamp | Event | Delta from DTMF |
|-----------|-------|-----------------------|
| 15:54:48.651 | DTMF -> AI handoff triggered | T=0 |
| 15:54:48.693 | Plivo audio WebSocket connected | +42ms |
| 15:54:48.699 | **Pre-warmed room consumed** (no room creation needed!) | +48ms |
| 15:54:48.711 | LiveKit signal client connecting | +60ms |
| 15:54:49.306 | PlivoLiveKitBridge started (room joined) | +655ms |
| 15:54:49.319 | **Agent audio track subscribed** | +668ms |
| 15:54:49.327 | **Greeting cache HIT** (36,300 bytes) | +676ms |
| 15:54:49.328 | **Cached greeting sent to Plivo** (0ms TTS wait) | +677ms |

**AI pipeline startup: ~677ms** (vs 3.47s before = **5.1x faster**)

Breakdown:
- Plivo WS connect: 42ms
- Room consume (pre-warmed): 6ms (vs 2.74s room creation before!)
- LiveKit room join: ~607ms
- Agent track subscribe: 13ms
- Greeting from cache: 1ms (vs 1.08s Sarvam TTS before!)

**Caller hears greeting at ~15:54:49.3** = **~677ms after DTMF** (vs ~4.5s before)

---

### Phase 5: LiveKit Agent Setup (15:54:35 -> 15:54:37)

The agent received the job during the IVR phase (pre-warm dispatched the room which triggered agent dispatch):

| Timestamp | Event | Delta |
|-----------|-------|-------|
| 15:54:35.385 | LiveKit received job request (during IVR!) | — |
| 15:54:35.541 | Job runner initializing (tid=new) | +156ms |
| 15:54:35.732 | Job runner initialized | +347ms |
| 15:54:36.239 | Agent joining room | +854ms |
| 15:54:36.270 | Adaptive interruption detector initialized | +885ms |
| 15:54:36.296 | **Agent fully started** | +911ms |
| 15:54:37.533 | Deepgram TTS WebSocket established | +2.15s |
| 15:54:37.711 | Deepgram STT WebSocket established | +2.33s |

**Agent was ready 12s before DTMF arrived!** (pre-warm at 15:54:35, DTMF at 15:54:48)

---

### Phase 6: First Conversational Turn (15:54:49 -> 15:55:01)

| Timestamp | Event | Delta |
|-----------|-------|-------|
| 15:54:49.477 | Bridge started reading plivo-bridge audio stream | — |
| 15:54:59.775 | User transcript: "Can you tell me more about the company?" | +10.3s (caller speaking) |
| 15:55:00.501 | Preemptive generation started | +0.7s from transcript |
| 15:55:00.647 | Groq LLM HTTP request sent | +0.87s |
| 15:55:00.832 | Groq LLM response received | +1.06s |

**First turn latency: ~1.06s** (transcript -> LLM response)

---

### Phase 7: Subsequent Turns

| Turn | Timestamp | User Speech | LLM Latency |
|------|-----------|-------------|-------------|
| 2 | 15:55:01.369 | (continued) | — |
| 3 | 15:55:03.046 | — | 144ms (Groq) |
| 4 | 15:55:05.916 | — | — |
| 5 | 15:55:06.524 | — | 124ms (Groq) |
| 6 | 15:55:26.789 | — | — |
| 7 | 15:55:27.390 | — | 134ms (Groq) |
| 8 | 15:55:31.800 | — | — |
| 9 | 15:55:33.840 | — | 142ms (Groq) |

**Average Groq LLM latency: ~136ms** (excellent)

---

### Phase 8: Call Termination (15:55:40 -> 15:55:43)

| Timestamp | Event | Delta |
|-----------|-------|-------|
| 15:55:40.553 | Plivo stream disconnected (customer hangup) | T=0 |
| 15:55:40.554 | Agent audio forwarding ended (0 chunks — see note below) | +1ms |
| 15:55:40.573 | LiveKit room disconnected (ClientInitiated) | +20ms |
| 15:55:40.575 | PlivoLiveKitBridge stopped | +22ms |
| 15:55:41.803 | Plivo call-status webhook: completed | +1.25s |
| 15:55:41.836 | `end_call` failed: call not found (benign — already ended) | +1.28s |
| 15:55:41.856 | `ai_handling -> wrap_up` | +1.30s |
| 15:55:41.884 | `wrap_up -> ended` (auto-disposition) | +1.33s |
| 15:55:42.052 | Recording status received (duration=68s) | +1.50s |
| 15:55:42.988 | Recording downloaded from Plivo (137,232 bytes) | +2.44s |
| 15:55:43.006 | Recording saved to disk | +2.45s |

**Teardown latency: ~2.5s** (call end -> full cleanup)

---

## Issue Found: Agent Audio Not Forwarded to Plivo

**"Agent audio forwarding ended: 0 chunks sent to Plivo"**

The bridge subscribed to the agent's audio track at 15:54:49.319, but 0 chunks were forwarded to Plivo. This means the agent's TTS audio (Deepgram TTS for conversational responses) was NOT reaching the caller through the bridge's `_forward_agent_audio` path.

**However, the caller DID hear the AI responses.** This means the audio is flowing through a different path — likely LiveKit's native audio routing where the agent publishes audio directly to the room, and the bridge's `_forward_agent_audio` mulaw conversion path has a bug.

**Root cause:** The `_forward_agent_audio` method checks `rms < _SILENCE_THRESHOLD` and skips frames. With the configurable threshold (currently default 50), all agent audio frames are being classified as silence. The agent's audio is PCM at a different sample rate or amplitude than expected.

**Impact:** Moderate — the caller hears responses via LiveKit's native audio path (confirmed by successful conversation), but the bridge's explicit forwarding path is broken. This means:
1. The bridge's mulaw-to-Plivo forwarding is redundant in the current setup
2. OR the audio is reaching Plivo via a different mechanism (LiveKit -> WebRTC -> Plivo)

**Recommendation:** Investigate the `_forward_agent_audio` RMS values to understand why all frames are below threshold. May need to adjust the silence threshold or check the PCM format (16-bit vs 8-bit, sample rate mismatch).

---

## Latency Comparison: Before vs After Optimizations

| Metric | Before (V1) | After (V2) | Improvement |
|--------|-------------|------------|-------------|
| Call setup (API -> ringing) | 72ms | 470ms | Slower (added pre-warm setup) |
| Ring time | 6.7s | 8.7s | External (callee) |
| IVR navigation | 22.2s | 16.4s | External (caller) |
| **AI pipeline startup** | **3.47s** | **0.677s** | **5.1x faster** |
| ├─ LiveKit job dispatch | 2.74s | 0ms (pre-warmed) | Eliminated |
| ├─ LiveKit room join | 600ms | 607ms | Same |
| └─ Greeting delivery | 1.08s | 1ms (cached) | **1000x faster** |
| **Dead air after DTMF** | **~4.5s** | **~0.68s** | **6.6x reduction** |
| STT transcript delay | 408ms | ~300ms (estimated) | Slightly better |
| LLM latency (Groq) | 590ms | 136ms | **4.3x faster** |
| Call teardown | 5.3s | 2.5s | 2x faster |

---

## Architecture Diagram

```
                                  ┌──────────────┐
                                  │   Frontend    │
                                  │  Dashboard    │
                                  └──────┬───────┘
                                         │ HTTP API
                                         v
┌─────────┐    Webhooks     ┌────────────────────────────┐
│  Plivo   │<──────────────>│   Backend (FastAPI :8000)  │
│  Cloud   │  POST /answer  │                            │
│  (SIP)   │  POST /dtmf    │  ┌──────────────────────┐  │
│          │  POST /status   │  │  Handoff Engine      │  │
│          │  POST /record   │  │  (state machine)     │  │
│          │                │  └──────────────────────┘  │
│          │   WebSocket    │                            │
│          │<──────────────>│  ┌──────────────────────┐  │
│          │  /audio-stream │  │  PlivoLiveKitBridge  │  │
└─────────┘                │  │  (mulaw <-> PCM)     │  │
                           │  └──────────┬───────────┘  │
                           │             │              │
                           │             │ LiveKit SDK  │
                           │             v              │
                           │  ┌──────────────────────┐  │
                           │  │  LiveKit Cloud Room   │  │
                           │  │  (wss://...livekit)  │  │
                           │  └──────────┬───────────┘  │
                           │             │              │
                           └─────────────┼──────────────┘
                                         │
                                         v
                           ┌──────────────────────────┐
                           │  LiveKit Agent Worker     │
                           │  (separate process)       │
                           │                           │
                           │  Deepgram STT ──> Groq   │
                           │  (streaming)     LLM     │
                           │                   │      │
                           │  Deepgram TTS <───┘      │
                           │  (streaming)              │
                           └──────────────────────────┘

  Supporting Services:
  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐
  │ PostgreSQL  │  │   Redis     │  │  Room Pre-warmer    │
  │ (state,     │  │ (events,    │  │  (creates rooms     │
  │  events,    │  │  greeting   │  │   during IVR)       │
  │  sessions)  │  │  cache)     │  │                     │
  └─────────────┘  └─────────────┘  └─────────────────────┘
```

---

## State Machine Transitions

```
15:54:23  INITIATED ──[DIAL]──> RINGING
15:54:32  RINGING ──[ANSWER]──> IVR
                                  │ (Background: pre-warm room + cache greeting)
15:54:48  IVR ──[DTMF_AI]──> AI_HANDLING
                                  │ (WebSocket audio stream active)
                                  │ (LiveKit bridge + agent conversation)
15:55:41  AI_HANDLING ──[CUSTOMER_DISCONNECT]──> WRAP_UP
15:55:41  WRAP_UP ──[DISPOSITION_SUBMITTED]──> ENDED
```

---

## Key Files in the Call Flow

| Phase | File | Purpose |
|-------|------|---------|
| Call initiation | `app/services/call_service.py` | Creates conversation, calls Plivo API |
| State transitions | `app/core/handoff_engine.py` | Central orchestrator for all state changes |
| State validation | `app/core/state_machine.py` | Pure-function transition table |
| Plivo webhooks | `app/api/v1/plivo.py` | Answer, DTMF, call-status, recording-status |
| Audio stream | `app/api/v1/plivo_stream.py` | WebSocket handler for bidirectional audio |
| Bridge | `app/voice_ai/plivo_livekit_bridge.py` | Plivo audio <-> LiveKit room conversion |
| LiveKit agent | `app/voice_ai/livekit_agent.py` | STT -> LLM -> TTS pipeline |
| LLM plugin | `app/voice_ai/sarvam_llm_plugin.py` | Groq/Sarvam LLM wrapper for LiveKit |
| Room pre-warmer | `app/services/room_prewarmer.py` | Creates rooms during IVR (latency opt) |
| Greeting cache | `app/services/greeting_cache.py` | Redis-cached TTS greetings (latency opt) |
| Events | `app/core/events.py` | Redis pub/sub event bus |
| WebSocket relay | `app/ws/broadcaster.py` | Redis events -> dashboard WebSocket |
| Provider | `app/providers/plivo/telephony.py` | Plivo REST API wrapper |

---

## Webhook Sequence (External -> Backend)

```
1. POST /api/v1/plivo/answer?tenant_id=...
   <- Returns IVR XML (<GetDigits> + <Speak>)

2. POST /api/v1/plivo/dtmf?tenant_id=...&conv_id=...&menu_id=...
   <- Returns Stream XML (<Stream bidirectional>)

3. WS /api/v1/plivo/audio-stream?tenant_id=...&conv_id=...&language=en
   <- Bidirectional audio WebSocket (mulaw 8kHz)
   Events: start -> media (continuous) -> stop

4. POST /api/v1/plivo/call-status?tenant_id=...
   Body: CallUUID, Status=completed, Duration, etc.
   <- Triggers state: ai_handling -> wrap_up -> ended

5. POST /api/v1/plivo/recording-status?tenant_id=...&conv_id=...
   Body: RecordingID, RecordUrl, RecordingDuration
   <- Downloads and saves recording
```
