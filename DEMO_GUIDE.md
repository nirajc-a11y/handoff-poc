# Demo Guide — Handoff POC

Complete walkthrough for running a fully functional demo with outbound calls, inbound calls, AI agent, supervisor barge-in, and live dashboard.

## 1. Prerequisites

- Python 3.11+
- Node.js 18+ with pnpm
- PostgreSQL (via Docker)
- ngrok (for phone call webhooks)

## 2. API Keys & Credentials

| Service | What You Need | Where to Get It |
|---------|--------------|-----------------|
| **PostgreSQL** | Local Docker (no signup) | `docker compose up -d postgres` |
| **Groq** | `GROQ_API_KEY` | https://console.groq.com/keys (free tier) |
| **Plivo** | `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN`, `PLIVO_NUMBER` | https://console.plivo.com — sign up, get a phone number |
| **Sarvam AI** | `SARVAM_API_KEY` | https://dashboard.sarvam.ai — sign up for Indian STT/TTS |
| **Twilio** (optional) | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_NUMBER` | https://console.twilio.com — only needed if using Twilio instead of Plivo |
| **ngrok** | Free account | https://ngrok.com — needed for Plivo/Twilio webhooks |

## 3. Environment Setup

```bash
# Clone and enter project
cd handoff-poc

# Start PostgreSQL
docker compose up -d postgres

# Install backend
pip install -e .

# Configure environment
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/handoff_poc
GROQ_API_KEY=gsk_xxxxxxxxxxxx
GROQ_MODEL=llama-3.3-70b-versatile

# Plivo (primary telephony)
PLIVO_AUTH_ID=MAxxxxxxxxxxxxxxxxxx
PLIVO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PLIVO_NUMBER=+918031140170

# Sarvam AI (Indian language STT/TTS)
SARVAM_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# ngrok URL (set after starting ngrok in step 5)
BASE_WEBHOOK_URL=https://xxxx-xxxx.ngrok-free.dev
```

## 4. Seed Database

```bash
python -m scripts.seed
```

This creates:
- 1 tenant (Demo Corp) — **save the tenant ID printed in output**
- 5 agents (available status)
- Bilingual IVR tree (English + Marathi)
- 1 campaign with 10 leads
- Plivo app configuration

## 5. Start ngrok

```bash
ngrok http 8000
```

Copy the `https://xxxx.ngrok-free.dev` URL and set it in `.env`:

```bash
BASE_WEBHOOK_URL=https://xxxx-xxxx.ngrok-free.dev
```

## 6. Configure Plivo Webhooks

```bash
python -m scripts.setup_plivo
```

This registers the ngrok URL with Plivo for answer/hangup/DTMF callbacks.

## 7. Start Backend

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verify: open http://localhost:8000/docs to see Swagger UI with 91+ endpoints.

## 8. Start Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

Open http://localhost:5173 and enter the **tenant ID** from step 4.

---

## Demo Scenarios

### Demo 1: Outbound Call with AI Agent

1. Open the dashboard at http://localhost:5173
2. Enter the tenant ID and click "Connect"
3. In the **Outbound Dialer** (right panel), enter a phone number and click **Dial**
4. Answer the call on your phone — you'll hear the IVR greeting
5. Press **1** for English (or **2** for Marathi)
6. Press **1** again to talk to the AI agent
7. The AI (Maya) greets you and starts conversing
8. Watch the **Messages** tab update in real-time with transcripts
9. Say **"hang up"** or **"bye"** to end the call
10. Check the **Handoffs** tab to see all state transitions

**Expected latency**: ~1.5-2s from when you stop speaking to AI response.

### Demo 2: AI Barge-In (User Interrupts AI)

1. Start an outbound call (same as Demo 1)
2. Let the AI start responding with a long answer
3. **Interrupt the AI by speaking** while it's talking
4. The AI should **stop immediately** and listen to you
5. Watch logs for: `Barge-in detected`, `Sent clearAudio`

### Demo 3: Supervisor Listen

1. Start a call (Demo 1)
2. While the AI is handling the call, click the **Supervise** tab in conversation detail
3. Click **Start Listening**
4. You should hear both the **caller** and **AI audio** through your browser speakers
5. The caller and AI don't know you're listening

### Demo 4: Supervisor Whisper

1. While listening to a call (Demo 3), type guidance in the **Whisper to AI** input
2. Example: "Tell the customer about our 50% discount on Pro plan"
3. Click send
4. When the customer speaks next, the AI will incorporate your guidance in its response
5. The customer never hears your whisper

### Demo 5: Supervisor Barge (Take Over Call)

1. While a call is active, go to the **Supervise** tab
2. Click **Take Over Call**
3. Confirm by clicking **Confirm: Mute AI & Take Over**
4. The AI immediately stops, the call is redirected to a conference room
5. The dashboard shows the conference name
6. Connect via the **Softphone** in the right panel (requires Plivo WebRTC credentials) to join the conference and talk to the customer directly

### Demo 6: Inbound Call

1. From any phone, dial your **Plivo number** (the one in `PLIVO_NUMBER`)
2. You'll hear the bilingual IVR:
   > "Welcome to Demo Corp. Press 1 for English. Demo Corp madhye aapale swaagat aahe. Marathisathi 2 daba."
3. Press **1** for English, then **1** for AI agent
4. Converse with the AI
5. The call appears in the dashboard under **Active** conversations

### Demo 7: AI Escalation to Human

1. Start a call and talk to the AI
2. Say **"I want to speak to a human"** or **"agent"**
3. The AI says "Let me transfer you now"
4. The state transitions to `QUEUED_FOR_HUMAN`
5. If an agent is available, they get assigned automatically
6. Watch the **Handoffs** tab for the escalation event

### Demo 8: Mock Demo (No Phone Provider Needed)

```bash
python -m scripts.demo --tenant-id <TENANT_ID>
```

Runs all 6 handoff scenarios via API calls — useful for testing state machine and dashboard without real phone calls.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "No active session" on supervisor listen | The call must be in `ai_handling` state (past IVR) |
| Phantom "Yes" echo after AI speaks | Check logs for `Echo guard: discarding` — if not appearing, increase `_cooldown_remaining` |
| Plivo `legs cannot be None` error | Ensure `legs="aleg"` is passed to `calls.update()` |
| Empty STT flooding (many empty transcripts) | Normal during silence — skipped automatically by RMS energy check |
| ngrok URL expired | Restart ngrok and update `BASE_WEBHOOK_URL` in `.env`, then restart server |
| Frontend not connecting | Ensure tenant ID is entered, check browser console for WS errors |
| Softphone not registering | Plivo WebRTC requires separate endpoint credentials (username/password from Plivo console) |

## Architecture Summary

```
Phone Call (Plivo/Twilio)
  |
  v
IVR (DTMF menu) --> AI Agent (Sarvam STT + Groq LLM + Sarvam TTS)
  |                    |                    |
  v                    v                    v
Human Queue     Supervisor Panel      Barge/Transfer
  |              Listen|Whisper|Barge       |
  v                    |                    v
Agent Softphone  <-----+            Conference Room
  |
  v
Wrap-Up --> Ended (disposition)
```

All state transitions are audited in `handoff_events`. All messages (customer, AI, agent, system) stored in `messages`. Full-call recordings saved in `recordings/`.
