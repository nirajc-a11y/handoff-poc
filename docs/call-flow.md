# Call Flow — Plivo PSTN → IVR → LiveKit Agent

This document traces the complete audio and data path for both inbound and outbound calls, from the moment Plivo receives a PSTN call through IVR navigation, LiveKit bridge, and the AI agent pipeline.

---

## Architecture Overview

```
PSTN Caller
  ↕ (SIP/PSTN)
Plivo
  ↕ (HTTP webhooks + WebSocket)
FastAPI Backend  (:8000)
  ├── /answer, /dtmf  → IVR XML responses
  ├── /audio-stream   → WebSocket (bidirectional audio)
  │     └── PlivoLiveKitBridge
  │           ↕ (LiveKit SDK, PCM audio tracks)
  │         LiveKit Server
  │           ↕ (LiveKit Agents SDK)
  │         LiveKit Agent Worker  (separate process)
  │           ├── Deepgram STT (streaming)
  │           ├── Groq LLM (streaming)
  │           └── Deepgram Aura / Sarvam Bulbul TTS
  └── HandoffEngine  → state machine + DB + Redis event bus
```

Two voice pipeline modes exist, toggled by `USE_LIVEKIT_AGENT` env var:

| Mode | Flag | Pipeline |
|---|---|---|
| **LiveKit Agent** (default new path) | `true` | Plivo WebSocket → PlivoLiveKitBridge → LiveKit room → Agent worker |
| **Legacy VoiceAISession** | `false` | Plivo WebSocket → VoiceAISession → Deepgram STT → Groq → Sarvam TTS directly |

This document focuses on **LiveKit Agent mode**.

---

## Inbound Call Flow

### Phase 1: Call Arrives → IVR

Plivo receives the PSTN call and immediately fires an HTTP POST to your configured Answer URL.

**Plivo → Backend:**
```
POST /api/v1/plivo/answer?tenant_id=<uuid>
Content-Type: application/x-www-form-urlencoded

From=+911234567890
To=+919876543210
CallUUID=abc-123-def-456
Direction=inbound
```

**What the backend does** ([plivo.py](../app/api/v1/plivo.py)):
1. Creates a `Conversation` record (`state=INITIATED`)
2. Creates a `ChannelSession` record linking `CallUUID` to the conversation
3. Runs state transitions: `INITIATED → RINGING → IVR` via `HandoffEngine`
4. **Background tasks** (non-blocking): pre-warm LiveKit room + cache TTS greeting in Redis
5. Fetches the IVR menu from DB for this tenant

**Backend → Plivo (Plivo XML):**
```xml
<Response>
  <GetDigits
    action="https://ngrok.../api/v1/plivo/dtmf?tenant_id=X&conv_id=Y&menu_id=Z"
    timeout="10"
    numDigits="1"
    retries="2">
    <Speak voice="Polly.Aditi" language="en-IN">
      Welcome. Press 1 for Sales. Press 2 for Support. Press 0 to repeat.
    </Speak>
  </GetDigits>
</Response>
```

Plivo plays the `<Speak>` audio to the caller and waits up to 10s for a digit.

---

### Phase 2: Caller Presses Digit → IVR Decision

**Plivo → Backend:**
```
POST /api/v1/plivo/dtmf?tenant_id=X&conv_id=Y&menu_id=Z
Content-Type: application/x-www-form-urlencoded

Digits=1
```

**What the backend does:**
1. Looks up digit "1" in the IVR menu → action type `ai_handoff`
2. State transition: `IVR → AI_HANDLING` via `Trigger.DTMF_AI`

**IVR action types and their results:**

| Action | Trigger | Next State | XML Response |
|---|---|---|---|
| `ai_handoff` | `DTMF_AI` | `AI_HANDLING` | `<Stream>` WebSocket URL |
| `human_queue` | `DTMF_HUMAN` | `QUEUED_FOR_HUMAN` | Hold music XML |
| `submenu` | — | stays `IVR` | New `<GetDigits>` |
| `play_message` | — | stays `IVR` | `<Speak>` + re-prompt |
| `hangup` | — | `WRAP_UP` | `<Hangup/>` |

---

### Phase 3: AI Handoff → Open WebSocket Stream

**Backend → Plivo (XML):**
```xml
<Response>
  <Stream
    bidirectional="true"
    contentType="audio/x-mulaw;rate=8000"
    keepCallAlive="true"
    streamTimeout="1800">
    wss://ngrok.../api/v1/plivo/audio-stream?tenant_id=X&conv_id=Y&language=en&speaker=ritu
  </Stream>
</Response>
```

Plivo immediately opens a **bidirectional WebSocket** to that URL and begins streaming raw audio in both directions. The call stays alive as long as the WebSocket is open.

---

### Phase 4: WebSocket Handshake

Handler: [plivo_stream.py](../app/api/v1/plivo_stream.py) → `_handle_livekit_bridge()`

**Plivo sends "start" event first:**
```json
{
  "event": "start",
  "start": {
    "streamId": "plivo-stream-001",
    "streamSid": "plivo-stream-001"
  }
}
```

On receiving `start`, the bridge:
1. Creates a `PlivoLiveKitBridge` instance
2. Joins LiveKit room `room-{conversation_id}` as participant `plivo-bridge`
3. Creates an `rtc.AudioSource` (24kHz PCM) and publishes it as track `caller-audio`
4. **Immediately streams cached TTS greeting** (mulaw → `playAudio` events) so the caller hears something while the agent worker finishes joining

---

### Phase 5: Ongoing Audio — Caller Speaking

Plivo sends a media frame every **20ms**:

```json
{
  "event": "media",
  "media": {
    "payload": "<base64 encoded mulaw bytes>",
    "contentType": "audio/x-mulaw",
    "sampleRate": 8000
  }
}
```

Each frame is 160 bytes of mulaw audio = 20ms at 8kHz.

**Bridge processing** ([plivo_livekit_bridge.py](../app/voice_ai/plivo_livekit_bridge.py) → `feed_audio()`):

```
base64.b64decode(payload)
  → 160 bytes mulaw @ 8kHz

audioop.ulaw2lin(mulaw, 2)
  → 320 bytes PCM 16-bit @ 8kHz

audioop.ratecv(pcm, 2, 1, 8000, 24000, None)
  → 960 bytes PCM 16-bit @ 24kHz

rtc.AudioFrame(sample_rate=24000, num_channels=1, samples_per_channel=480)
  → published to LiveKit room as "caller-audio" track
```

---

### Phase 6: LiveKit Agent Pipeline

The agent worker ([livekit_agent.py](../app/voice_ai/livekit_agent.py)) runs as a **separate process** (`python -m app.voice_ai.livekit_agent`). It auto-joins any room matching the room-name pattern and reads configuration from the room's metadata JSON:

```json
{
  "tenant_id": "uuid",
  "conversation_id": "uuid",
  "language": "en",
  "company_name": "Demo Corp",
  "ai_system_prompt": "You are a helpful customer support agent..."
}
```

**STT → LLM → TTS pipeline:**

```
LiveKit "caller-audio" track
  ↓
Deepgram nova-3 (streaming STT)
  – real-time interim transcripts while caller speaks
  – Silero VAD detects end of utterance
  ↓
Groq llama-4-scout-17b (LLM, streaming)
  – sentences arrive incrementally
  ↓
Per-sentence TTS (immediately, no wait for full response)
  – English  → Deepgram Aura 2
  – Hindi / Marathi → Sarvam Bulbul v3
  ↓
TTS audio published as agent's audio track in the room
```

**Latency budget:** ~1.5–2.0s turn latency end-to-end (VAD end → first audio played back). First turn ~0.3–0.5s faster due to reduced AEC warmup (0.3s vs 1.5s).

**Transcript persistence** — the agent worker has no DB connection. Transcripts flow via Redis:

```
livekit_agent.py
  → publish to Redis channel "transcript.added":
    {
      "conversation_id": "uuid",
      "tenant_id": "uuid",
      "sender_type": "customer" | "ai",
      "content": "Hello, I need help with my bill"
    }

transcript_handler.py (FastAPI main process, subscribed to "transcript.added")
  → saves Message record to DB
  → publishes "conversation.message_added" to event bus
  → WebSocket broadcaster relays to dashboard clients
```

---

### Phase 7: Agent Speaking — Audio Back to Caller

When the agent's TTS audio track is published, the bridge subscribes automatically:

```
Agent's TTS audio track (PCM 16-bit @ 24kHz)
  ↓ bridge._on_track_subscribed() fires
  ↓ rtc.AudioStream(track, sample_rate=24000, num_channels=1)  ← receives at native 24kHz
  ↓ async for frame in audio_stream:
      audioop.lin2ulaw(frame.data, 2)
      → mulaw @ 8kHz
      buffer in 160-byte chunks

  ↓ WebSocket send to Plivo:
    {
      "event": "playAudio",
      "streamId": "plivo-stream-001",
      "media": {
        "payload": "<base64 mulaw 160 bytes>",
        "contentType": "audio/x-mulaw",
        "sampleRate": 8000
      }
    }
```

Plivo plays the audio to the caller in real time.

---

### Phase 8: Barge-In (Caller Interrupts Agent)

Silero VAD (inside the LiveKit agent) detects the caller speaking while the agent is playing back audio.

```
Agent detects barge-in
  ↓
Publishes LiveKit data message to room:
  {"type": "barge_in"}
  ↓
Bridge._on_data() receives it
  ↓
Bridge sends to Plivo WebSocket:
  {"event": "clearAudio", "streamId": "plivo-stream-001"}
  ↓
Plivo immediately discards queued audio
  ↓
Agent's in-progress LLM/TTS pipeline is cancelled
  ↓
Caller's new speech is processed as the next turn
```

---

### Phase 9: Escalation to Human

Caller says "I want to speak to a person" → agent's `transfer_to_human` function tool fires:

```
Agent tool: transfer_to_human()
  ↓
_trigger_escalation() — in-process call (no HTTP):
  handoff_engine.process_trigger(trigger=Trigger.AI_TRANSFER, ...)
  ↓
HandoffEngine: AI_HANDLING → QUEUED_FOR_HUMAN
  – DB: conversation.queue_entered_at = now
  – Redis event: "queue.conversation_queued"
  ↓
Routing engine finds available agent
  ↓
HandoffEngine: QUEUED_FOR_HUMAN → HUMAN_HANDLING
  – DB: conversation.current_handler_id = agent_uuid
  – LiveKit data message to room:
    {"type": "agent_assigned", "agent_id": "uuid", "conversation_id": "uuid"}
  ↓
Human agent connects via browser softphone (Plivo WebRTC)
```

---

### Phase 10: Call End

Agent tool `end_call()` fires, or caller disconnects:

```
HandoffEngine: AI_HANDLING → WRAP_UP → ENDED
  – DB: conversation.ended_at = now
  – LiveKit room deleted
  – Redis event: "conversation.ended"
  ↓
Plivo WebSocket closes
  ↓
Plivo fires status callback to /api/v1/plivo/status
```

---

## Outbound Call Flow

### Phase 1: Initiate the Call

```
POST /api/v1/calls/outbound
{
  "to_number": "+911234567890",
  "customer_name": "Rahul Sharma",
  "campaign_lead_id": "uuid"
}
  ↓
Conversation(state=INITIATED, direction=outbound) created in DB
  ↓
provider.initiate_call() → Plivo REST API dials the customer
  ↓
Trigger.DIAL → state: RINGING
  ↓
Return conversation_id to caller (frontend polls for state updates)
```

### Phase 2: Customer Picks Up → Same Webhook

When the customer answers, Plivo fires the same `/answer` webhook — but with `Direction: outbound`:

```
POST /api/v1/plivo/answer?tenant_id=<uuid>

From=+919876543210   ← your Plivo number
To=+911234567890     ← customer's number
CallUUID=xyz-789
Direction=outbound
```

**Key difference from inbound** ([plivo.py:130](../app/api/v1/plivo.py)):

```python
# Inbound: customer is the caller
customer_number = from_number if direction == "inbound" else to_number

# Outbound: customer is the one you dialed
customer_number = to_number if direction == "outbound" else from_number
```

For outbound, `_find_or_create_conversation()` finds the **existing** conversation (already at `RINGING`) by matching `CallUUID` rather than creating a new one.

From this point, the flow is **identical to inbound**: state advances `RINGING → IVR`, the same XML is returned, and the same WebSocket stream is opened.

---

## Why One Webhook for Both Directions?

Plivo's architecture ties the Answer URL to the **Plivo application** (configured once), not to the call direction. When any call — inbound or outbound — is answered, Plivo fires that URL. The `Direction` field in the POST body tells the backend which way the call was initiated.

The backend handles this in two places:

1. **Customer number resolution** — determines which phone number belongs to the customer vs. the platform.
2. **Conversation lookup** — outbound finds an existing record; inbound creates one.

Everything downstream (IVR, WebSocket stream, LiveKit bridge) is direction-agnostic.

---

## Audio Encoding Reference

| Path | Encoding | Sample Rate | Frame Size | Duration |
|---|---|---|---|---|
| Plivo → Bridge (media event) | mulaw | 8 kHz | 160 bytes | 20ms |
| Bridge → LiveKit (feed_audio) | PCM 16-bit | 24 kHz | 960 bytes | 20ms |
| LiveKit agent track (internal) | PCM 16-bit | 24 kHz | variable | — |
| LiveKit → Bridge (participant) | PCM 16-bit | 8 kHz | 160 bytes | 20ms |
| Bridge → Plivo (playAudio) | mulaw | 8 kHz | 160 bytes | 20ms |

**Conversion functions used** (`audioop` stdlib):
- mulaw → PCM: `audioop.ulaw2lin(data, 2)`
- PCM → mulaw: `audioop.lin2ulaw(data, 2)`
- Resample: `audioop.ratecv(data, 2, 1, from_rate, to_rate, None)`

---

## State Machine Summary

```
INITIATED
  ↓ RING
RINGING
  ↓ ANSWER
IVR
  ↓ DTMF_AI          ↓ DTMF_HUMAN
AI_HANDLING      QUEUED_FOR_HUMAN
  ↓ CUSTOMER_ESCALATION   ↓ AGENT_ASSIGNED
              HUMAN_HANDLING
              ↕ AGENT_HOLD / AGENT_UNHOLD
              ON_HOLD
                  ↓ AGENT_END / CUSTOMER_DISCONNECT
              WRAP_UP
                  ↓ DISPOSITION_SUBMITTED
              ENDED
```

All transitions go through `HandoffEngine.process_trigger()` which:
1. Acquires a row-level DB lock (`SELECT FOR UPDATE`) — no race conditions
2. Validates via pure-function state machine
3. Executes side effects (provider calls, LiveKit data messages, routing)
4. Persists a `HandoffEvent` audit record
5. Publishes to Redis event bus → WebSocket broadcaster → dashboard

---

## Key Files

| File | Role |
|---|---|
| [app/api/v1/plivo.py](../app/api/v1/plivo.py) | `/answer`, `/dtmf` webhook handlers, IVR XML generation |
| [app/api/v1/plivo_stream.py](../app/api/v1/plivo_stream.py) | WebSocket handler for `/audio-stream` |
| [app/voice_ai/plivo_livekit_bridge.py](../app/voice_ai/plivo_livekit_bridge.py) | mulaw↔PCM conversion, LiveKit room join/audio routing |
| [app/voice_ai/livekit_agent.py](../app/voice_ai/livekit_agent.py) | Agent worker: Deepgram STT + Groq LLM + TTS pipeline |
| [app/core/handoff_engine.py](../app/core/handoff_engine.py) | Central state orchestrator (all state transitions) |
| [app/core/state_machine.py](../app/core/state_machine.py) | Pure transition table (11 states, 24 triggers) |
| [app/services/transcript_handler.py](../app/services/transcript_handler.py) | Redis `transcript.added` → DB `Message` persistence |
| [app/voice_ai/sarvam.py](../app/voice_ai/sarvam.py) | Sarvam STT + TTS (Hindi/Marathi) |
| [app/services/room_prewarmer.py](../app/services/room_prewarmer.py) | Pre-creates LiveKit rooms during IVR to eliminate dispatch delay |
