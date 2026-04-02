# Angel Tel — Handoff POC

Multi-tenant telecom handoff orchestration engine. Demonstrates real-time IVR / AI / Human agent handoffs across Voice, WhatsApp, Email, and SMS channels with a live operations dashboard.

## Features

- **6 Handoff Scenarios** — IVR->AI, AI->Human, Human->Human transfer, IVR skip, WhatsApp escalation, Email threading
- **Real Phone Calls** — Twilio and Plivo integration with pluggable provider architecture
- **AI Agent** — Groq-powered (Llama 3) conversational AI with streaming LLM + streaming TTS (~1.5s turn latency)
- **Barge-In** — Caller can interrupt AI mid-sentence; system detects speech, stops TTS, processes new input
- **Echo Suppression** — Playback wait + echo guard prevents phantom transcript pickup
- **Supervisor Panel** — Live Listen (hear call audio), Whisper (guide AI without customer hearing), Barge (take over call)
- **Bilingual IVR** — English + Marathi language selection with language-aware AI responses
- **Call Recording** — Automatic recording saved to `recordings/` folder
- **Live Transcription** — Real-time speech-to-text via Sarvam (Indian languages) and Twilio
- **Browser Softphone** — WebRTC-based agent softphone (Plivo Browser SDK) with mute, hold, transfer
- **Live Dashboard** — Real-time operations center showing conversations, agents, queue metrics, event feed
- **Multi-tenant** — All data scoped by `tenant_id` from day one
- **Multi-channel** — Voice, WhatsApp, Email, SMS with unified conversation model

## Architecture

```
                    ┌──────────────────────────────────┐
                    │     Live Operations Dashboard     │
                    │  (WebSocket + Plivo Softphone)    │
                    └───────────────┬──────────────────┘
                                    │ events
                    ┌───────────────┴──────────────────┐
                    │          Event Bus                │
                    │   (in-process async pub/sub)      │
                    └───────────────┬──────────────────┘
                                    │
  ┌──────────┐   ┌──────────┐  ┌────┴──────────┐  ┌────────────────┐
  │ REST API │──>│ Services │──│ HandoffEngine │──│   Providers    │
  │  (87+    │   │          │  │ (orchestrator)│  │  (pluggable)   │
  │ routes)  │   │          │  │               │  │                │
  └──────────┘   └──────────┘  └───────────────┘  └────────────────┘
                                      │                    │
                                ┌─────┴─────┐    ┌────────┴────────┐
                                │   State   │    │  Twilio / Plivo  │
                                │  Machine  │    │  Mock WhatsApp   │
                                │ (11 states│    │  Mock Email/SMS  │
                                │ 24 triggers)   └─────────────────┘
                                └───────────┘
```

**Core concept:** Every interaction (call, chat, email) is a **Conversation** moving through a state machine. The **HandoffEngine** orchestrates transitions between IVR → AI → Human across all channels.

## Quick Start

### Prerequisites
- Python 3.11+
- Docker (for PostgreSQL)
- Node.js 18+ and pnpm (for frontend)
- ngrok (for real phone calls)

### Single Command Setup

```bash
# First time (installs deps, seeds DB, starts everything):
pip install -e .
cd frontend && pnpm install && cd ..
bash scripts/dev.sh --seed

# Subsequent runs (just start everything):
bash scripts/dev.sh
```

This single command:
1. Starts PostgreSQL via Docker Compose
2. Starts ngrok (auto-detects static domain from `.env`)
3. Updates `BASE_WEBHOOK_URL` in `.env` with the ngrok URL
4. Updates Plivo application webhook URLs via API
5. Starts the backend (uvicorn on `:8000` with hot-reload)
6. Starts the frontend (Vite on `:5173` with proxy to backend)

**Ctrl+C** stops all services cleanly. PostgreSQL container stays running.

**Flags:**

| Flag         | Description                                      |
|--------------|--------------------------------------------------|
| `--seed`     | Seed the database (first run, or to reset data)  |
| `--no-ngrok` | Skip ngrok (for mock/local-only testing)         |

### Manual Setup (step by step)

```bash
# 1. Start PostgreSQL
docker compose up -d postgres

# 2. Install dependencies
pip install -e .

# 3. Configure environment
cp .env.example .env
# Edit .env with your credentials (see Environment Variables below)

# 4. Seed database (creates tenant, agents, bilingual IVR, campaign, leads)
python -m scripts.seed

# 5. Start the server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 6. Start frontend (separate terminal)
cd frontend && pnpm dev

# 7. Open dashboard
# http://localhost:5173?tenant_id=<TENANT_ID_FROM_SEED>
```

### Mock Demo (no phone provider needed)

```bash
# Run all 6 handoff scenarios via API
python -m scripts.demo --tenant-id <TENANT_ID>
```

### Real Phone Calls (Twilio)

```bash
# 1. Start ngrok
ngrok http 8000

# 2. Set BASE_WEBHOOK_URL in .env to your ngrok URL

# 3. Configure Twilio webhooks
python -m scripts.setup_twilio

# 4. Call your Twilio number — hear bilingual IVR!
```

## Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/handoff_poc

# AI (optional — mock fallback works without it)
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile

# Twilio (for real phone calls)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxx
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_NUMBER=+15186174139

# Plivo (alternative telephony provider)
PLIVO_AUTH_ID=MAxxxxxxxxxx
PLIVO_AUTH_TOKEN=your-auth-token
PLIVO_NUMBER=+91xxxxxxxxxx

# Webhook URL (ngrok URL for Twilio/Plivo callbacks)
BASE_WEBHOOK_URL=https://your-ngrok-url.ngrok-free.dev
```

## Handoff Scenarios

| # | Scenario | Flow | Channel |
|---|----------|------|---------|
| 1 | Inbound + AI escalation | Call → IVR → AI → confidence drops → Human | Voice |
| 2 | IVR skip to human | Call → IVR → Press 0 → Human queue → Agent assigned | Voice |
| 3 | Human-to-human transfer | Agent A → warm/cold transfer → Agent B | Voice |
| 4 | Outbound campaign | Campaign → auto-dial lead → Agent handles | Voice |
| 5 | WhatsApp + AI escalation | Message → AI responds → "agent" keyword → Human | WhatsApp |
| 6 | Email threading | Inbound email → thread matching → AI/Human | Email |

## State Machine

```
INITIATED → RINGING → IVR → AI_HANDLING → QUEUED_FOR_HUMAN → HUMAN_HANDLING → WRAP_UP → ENDED
                        │         │                                │
                        │         └→ QUEUED (confidence drop)      ├→ ON_HOLD
                        │                                          ├→ TRANSFERRED
                        └→ HUMAN (press 0, skip AI)                └→ WRAP_UP
```

11 states, 24 triggers, all transitions audited in `handoff_events` table.

## Bilingual IVR (English + Marathi)

When a customer calls, they hear:

> "Welcome to Demo Corp. Press 1 for English.
> डेमो कॉर्प मध्ये आपले स्वागत आहे. मराठीसाठी 2 दाबा."

- **Press 1** → English menu → English AI agent
- **Press 2** → Marathi menu → Marathi AI agent (via Groq Llama 3)

Language selection flows through the entire conversation — IVR prompts, AI responses, and escalation keywords are all language-aware.

## Call Recording & Transcription

- **Recording**: Automatically enabled on Twilio calls. Saved to `recordings/` folder as `.wav` files.
- **Transcription**: Real-time transcription via Twilio. Appears in dashboard transcript tab and stored as messages.
- **Playback**: Recordings accessible via `/recordings/{filename}` static URL and audio player in dashboard.

## Live Dashboard

Open `http://localhost:8000/static/index.html?tenant_id=<TENANT_ID>` for:

- **Active Conversations** — Real-time list with state badges, channel icons, handlers, duration timers
- **Conversation Detail** — Message thread, transcript tab, action buttons (hold, transfer, escalate, end, disposition)
- **Agent Status Grid** — Live agent availability with click-to-toggle
- **Outbound Dialer** — Click-to-call with phone number input
- **Campaign Panel** — Progress tracking with "Dial Next Lead" button
- **Queue Metrics** — Depth, avg wait, by-skill breakdown
- **Handoff Event Feed** — Real-time scrolling log of all state transitions
- **Browser Softphone** — Plivo WebRTC integration for answering/making calls in browser

## API Documentation

**Swagger UI**: http://localhost:8000/docs

### Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/calls/outbound` | POST | Initiate outbound call |
| `/api/v1/calls/inbound/webhook` | POST | Inbound call webhook |
| `/api/v1/calls/{id}/answer` | POST | Answer/connect a call |
| `/api/v1/calls/{id}/hold` | POST | Put call on hold |
| `/api/v1/calls/{id}/transfer` | POST | Transfer to another agent |
| `/api/v1/calls/{id}/end` | POST | End call |
| `/api/v1/handoffs/escalate` | POST | AI → human escalation |
| `/api/v1/handoffs/transfer` | POST | Human → human transfer |
| `/api/v1/handoffs/queue` | GET | View waiting queue |
| `/api/v1/handoffs/queue/stats` | GET | Queue metrics |
| `/api/v1/conversations` | GET | List conversations |
| `/api/v1/conversations/{id}` | GET | Conversation detail + messages |
| `/api/v1/conversations/{id}/disposition` | POST | Submit call disposition |
| `/api/v1/channels/whatsapp/webhook` | POST | Inbound WhatsApp |
| `/api/v1/channels/email/webhook` | POST | Inbound email |
| `/api/v1/channels/sms/webhook` | POST | Inbound SMS |
| `/api/v1/campaigns` | GET | List campaigns |
| `/api/v1/campaigns/{id}/next-lead` | POST | Get next lead to dial |
| `/api/v1/agents` | GET | List agents with status |
| `/api/v1/agents/{id}/status` | PATCH | Update agent status |
| `/api/v1/twilio/answer` | POST | Twilio TwiML answer webhook |
| `/api/v1/twilio/dtmf` | POST | Twilio DTMF handler |
| `/api/v1/ws/dashboard` | WS | Live dashboard WebSocket |
| `/api/v1/supervisor/listen/{id}` | WS | Stream live caller+AI audio to supervisor |
| `/api/v1/supervisor/whisper/{id}` | POST | Inject guidance into AI (customer can't hear) |
| `/api/v1/supervisor/barge/{id}` | POST | Mute AI, take over call via conference |
| `/api/v1/supervisor/active-sessions` | GET | List active AI voice sessions |

91+ total endpoints. See full list at `/docs`.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI + Uvicorn |
| Database | PostgreSQL + async SQLAlchemy + Alembic |
| AI | Groq SDK (Llama 3.3 70B) with streaming + mock fallback |
| STT/TTS | Sarvam AI (Indian languages: English, Marathi, Hindi) |
| Telephony | Twilio Voice + Plivo (pluggable) |
| Browser Calling | Plivo Browser SDK (WebRTC) |
| Real-time | WebSocket (FastAPI native) |
| Frontend | React 19 + TailwindCSS v4 + shadcn/ui |
| IVR | Twilio TwiML / Plivo XML |
| Recording | Full-call recording via Plivo/Twilio → local `.mp3` files |
| Supervision | Live Listen + Whisper + Barge via WebSocket + conference |

## Project Structure

```
handoff-poc/
├── app/
│   ├── api/v1/                 # REST + WebSocket endpoints
│   │   ├── calls.py            #   Voice call lifecycle
│   │   ├── conversations.py    #   Conversation CRUD
│   │   ├── handoffs.py         #   Escalation & transfer
│   │   ├── agents.py           #   Agent management
│   │   ├── campaigns.py        #   Campaign & lead management
│   │   ├── leads.py            #   Lead CRUD + import
│   │   ├── tenants.py          #   Tenant setup
│   │   ├── ivr.py              #   IVR menu config
│   │   ├── twilio.py           #   Twilio TwiML webhooks (9 endpoints)
│   │   ├── plivo.py            #   Plivo XML webhooks (7 endpoints)
│   │   ├── plivo_stream.py     #   Plivo bidirectional audio stream (AI voice)
│   │   ├── supervisor.py       #   Supervisor Listen/Whisper/Barge endpoints
│   │   ├── webhooks.py         #   Generic provider webhooks
│   │   ├── ws.py               #   WebSocket dashboard endpoint
│   │   └── channels/           #   WhatsApp, Email, SMS endpoints
│   ├── core/
│   │   ├── state_machine.py    #   11 states, 24 triggers, transition table
│   │   ├── handoff_engine.py   #   Central orchestrator (most important file)
│   │   ├── events.py           #   Async event bus with glob matching
│   │   ├── ai_engine.py        #   Groq AI with streaming LLM + bilingual support
│   │   ├── ivr_engine.py       #   IVR menu traversal
│   │   ├── routing_engine.py   #   Agent routing (skill-based, least-loaded)
│   │   └── context_builder.py  #   Handoff context payloads
│   ├── db/models/              #   14 SQLAlchemy models
│   │   ├── conversation.py     #   Core unified conversation entity
│   │   ├── message.py          #   Messages (text, audio, transcription)
│   │   ├── handoff_event.py    #   Audit trail for every handoff
│   │   └── ...                 #   tenant, user, agent, campaign, lead, etc.
│   ├── providers/
│   │   ├── base.py             #   Abstract interfaces (4 channel providers)
│   │   ├── registry.py         #   Provider registry (per-tenant resolution)
│   │   ├── twilio/             #   Twilio Voice implementation
│   │   ├── plivo/              #   Plivo Voice implementation
│   │   └── mock/               #   Mock providers for all channels
│   ├── voice_ai/
│   │   ├── voice_agent.py      #   VoiceAISession (barge-in, streaming, echo guard)
│   │   ├── sarvam.py           #   Sarvam STT/TTS client (shared httpx pool)
│   │   └── session_registry.py #   Active session tracking for supervisor
│   ├── services/               #   Business logic layer (7 services)
│   └── ws/                     #   WebSocket manager + event broadcaster
├── scripts/
│   ├── dev.sh                  #   Single command: start full stack (pg + ngrok + backend + frontend)
│   ├── seed.py                 #   Seed demo data (bilingual IVR, agents, leads)
│   ├── demo.py                 #   Run all 6 handoff scenarios
│   ├── setup_twilio.py         #   Configure Twilio webhooks + verify numbers
│   ├── setup_plivo.py          #   Create Plivo app + endpoints
│   ├── update_webhooks.py      #   Update Plivo app webhook URLs from BASE_WEBHOOK_URL
│   └── verify_number.py        #   Verify caller IDs
├── static/
│   └── index.html              #   Live operations dashboard + softphone
├── recordings/                 #   Call recordings (.wav files)
├── docker-compose.yaml         #   PostgreSQL + app
├── pyproject.toml              #   Python dependencies
└── alembic/                    #   Database migrations
```

## Database Schema

14 tables, all tenant-scoped:

| Table | Purpose |
|-------|---------|
| `tenants` | Tenant config (provider settings, AI thresholds, language) |
| `users` | Users with roles (agent, supervisor, admin) |
| `agent_profiles` | Agent skills, team, max concurrent capacity |
| `agent_statuses` | Real-time agent availability |
| `conversations` | Core entity — unified across all channels |
| `messages` | Messages, recordings, transcriptions |
| `handoff_events` | Audit trail for every state transition |
| `channel_sessions` | Provider-level session mapping |
| `campaigns` | Outbound campaign management |
| `leads` | Customer leads with contact info |
| `campaign_leads` | Lead assignment and disposition tracking |
| `support_tickets` | Auto-created from conversations |
| `ivr_menus` | Configurable IVR menu trees |
| `ivr_menu_options` | DTMF → action mappings |

## Provider Architecture

Pluggable provider interfaces allow swapping telephony providers without changing business logic:

```python
# Abstract interface
class TelephonyProvider(ABC):
    async def initiate_call(request) -> CallResult
    async def transfer_call(call_id, target, warm) -> CallResult
    async def hold_call(call_id) -> CallResult
    async def end_call(call_id) -> CallResult
    # ... 9 methods total

# Implementations
class TwilioTelephonyProvider(TelephonyProvider): ...
class PlivoTelephonyProvider(TelephonyProvider): ...
class MockTelephonyProvider(TelephonyProvider): ...
```

Same pattern for WhatsApp, Email, and SMS providers.

## Cleanup

To stop Twilio charges:
1. Go to Twilio Console → Phone Numbers → Active Numbers
2. Click your number → **Release this number**
3. Trial credit stops being consumed

## License

Internal POC — Angel Tel / Vsynergize
