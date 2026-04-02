# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Handoff POC is a multi-tenant telecom handoff orchestration engine. It demonstrates real-time IVR / AI / Human agent handoffs across Voice, WhatsApp, Email, and SMS channels with a live operations dashboard and supervisor panel.

Two independent sub-projects:
- **Backend** (root `app/`) — Python FastAPI with async SQLAlchemy, Alembic migrations
- **Frontend** (`frontend/`) — React 19 SPA with Vite, TailwindCSS v4, shadcn/ui

## Development Commands

### Single Command (recommended)
```bash
bash scripts/dev.sh              # Start full stack: postgres + ngrok + backend + frontend
bash scripts/dev.sh --seed       # Also seed the database (first run or reset)
bash scripts/dev.sh --no-ngrok   # Skip ngrok (mock/local-only testing)
```

`dev.sh` orchestrates: Docker PostgreSQL -> ngrok (auto-detects static domain from `.env`) -> updates `BASE_WEBHOOK_URL` in `.env` -> updates Plivo app webhooks via API -> uvicorn `:8000` -> pnpm dev `:5173`. Ctrl+C stops all.

### Backend (project root)
```bash
docker compose up -d postgres          # Start PostgreSQL
pip install -e .                        # Install dependencies (editable)
pip install -e ".[dev]"                 # Include dev deps (pytest, pytest-asyncio)
python -m scripts.seed                  # Seed demo data (tenant, agents, IVR, campaign, leads)
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000  # Dev server
python -m scripts.demo --tenant-id <ID> # Run all 6 handoff scenarios (mock, no provider needed)
python -m scripts.update_webhooks      # Update Plivo app webhook URLs from BASE_WEBHOOK_URL
```

### Frontend (`frontend/`)
```bash
pnpm install
pnpm dev              # Dev server on http://localhost:5173 (proxies /api and /ws to :8000)
pnpm build            # tsc + vite build
```

### Database Migrations
```bash
alembic upgrade head                           # Apply all migrations
alembic revision --autogenerate -m "message"   # Generate new migration
```
Note: `scripts/seed.py` uses `Base.metadata.create_all` and skips Alembic for dev convenience.

### No test suite or linter is currently configured (pytest scaffolding exists in `pyproject.toml`).

## Architecture

### Core Orchestration Pattern

Every interaction (call, chat, email) is a **Conversation** moving through a state machine. The **HandoffEngine** (`app/core/handoff_engine.py`) is the central orchestrator — all conversation state mutations must go through `HandoffEngine.process_trigger()`. It:
1. Acquires a row-level lock (`SELECT FOR UPDATE`)
2. Validates transition via the pure-function state machine
3. Executes side effects (routing, provider calls, context building)
4. Persists a `HandoffEvent` audit record
5. Publishes to the in-process async event bus

### State Machine (`app/core/state_machine.py`)
11 states, 24 triggers. Pure function: `transition(state, trigger) -> (new_state, event_type)`. No side effects — the transition table is a dict mapping `(ConversationState, Trigger)` tuples.

States: `INITIATED -> RINGING -> IVR -> AI_HANDLING -> QUEUED_FOR_HUMAN -> HUMAN_HANDLING -> WRAP_UP -> ENDED` (plus `ON_HOLD`, `TRANSFERRED`, `FAILED`).

### Event Bus (`app/core/events.py`)
In-process async pub/sub with fnmatch glob patterns. The `WSBroadcaster` subscribes to `conversation.*` and pushes events to WebSocket clients. Module-level singleton: `event_bus`.

### Provider Architecture (`app/providers/`)
Pluggable ABC interfaces for 4 channels: `TelephonyProvider`, `WhatsAppProvider`, `EmailProvider`, `SMSProvider` (defined in `base.py`). The `ProviderRegistry` resolves per-tenant provider from tenant config JSONB (`{"providers": {"telephony": "twilio"}}`). Falls back to mock providers automatically.

Implementations: Twilio, Plivo (voice only), Mock (all channels). Providers are registered at startup in `app/main.py` lifespan based on env var presence.

### Real-time Voice AI (`app/livekit/voice_agent.py`)

Production-grade bidirectional voice AI pipeline:

```
Plivo audio stream (mulaw 8kHz)
  -> VoiceAISession.add_audio() [silence detection + barge-in monitoring]
  -> Sarvam STT (streaming via shared httpx pool)
  -> Groq LLM (streaming sentences via _call_groq_stream)
  -> Sarvam TTS (streaming per-sentence via synthesize_stream)
  -> mulaw chunks back to Plivo
```

**Key features:**
- **Streaming pipeline**: LLM streams sentences -> each sentence immediately sent to TTS -> mulaw chunks sent to Plivo as they arrive. First audio reaches caller in ~500ms.
- **Barge-in**: Tri-state machine (`LISTENING`/`SPEAKING`/`BARGE_IN`). During TTS playback, RMS energy is monitored. 3 consecutive high-energy frames trigger barge-in -> `clearAudio` sent to Plivo, TTS/LLM pipeline cancelled.
- **Echo suppression**: (1) Playback wait — calculates audio duration from bytes sent, waits for Plivo to finish before listening. (2) Post-TTS cooldown (0.6s). (3) Echo guard — discards short phantom transcripts ("Yes", "Yeah") on first utterance after TTS.
- **Shared httpx pool**: Module-level `httpx.AsyncClient` in `sarvam.py` reuses TCP+TLS connections (~300-600ms saved per turn).
- **Tuned thresholds**: Silence detection 0.6s (industry standard), cooldown 0.6s, min speech 0.3s.

Latency budget: ~1.5-2.0s turn latency (down from ~4.5s). See `VOICE_AI_FINDINGS.md` for full analysis.

### Supervisor Subsystem

Live call supervision with Listen, Whisper, and Barge modes:

- **Session Registry** (`app/livekit/session_registry.py`): Module-level dict tracking active `VoiceAISession` instances by `conversation_id`. Stores session, Plivo WebSocket, stream_sid, and listener queues. Registered/unregistered in `plivo_stream.py`.
- **Listen** (`WS /api/v1/supervisor/listen/{conv_id}`): Forwards a copy of caller + AI audio to supervisor browser via WebSocket. Frontend decodes mulaw and plays via Web Audio API.
- **Whisper** (`POST /api/v1/supervisor/whisper/{conv_id}`): Injects supervisor guidance as a system message into `conversation_history`. AI incorporates it in the next response. Customer never hears it.
- **Barge** (`POST /api/v1/supervisor/barge/{conv_id}`): Cancels AI pipeline (`_barge_in_event`), sends `clearAudio`, transitions to `QUEUED_FOR_HUMAN`, redirects Plivo call to conference room. Supervisor joins via browser softphone.

### API Layer
All routes under `/api/v1/` via `app/api/v1/router.py`. 91+ endpoints. Swagger at `/docs`. Multi-tenancy enforced via `X-Tenant-Id` header (see `app/dependencies.py`).

### Frontend
React 19 + Vite + TailwindCSS v4. Path alias `@/` maps to `./src/`. Pages: live dashboard, agents, campaigns, analytics, IVR config, history, settings. Browser softphone (Plivo WebRTC) in right panel. Supervisor panel in conversation detail (Listen/Whisper/Barge controls). State via Jotai atoms (`src/stores/`), data fetching via TanStack React Query. Vite proxies `/api`, `/ws`, `/recordings` to backend at `:8000`.

### Module-Level Singletons
Core engines are instantiated as module-level singletons at the bottom of their files: `handoff_engine`, `event_bus`, `routing_engine`, `ai_engine`, `ivr_engine`, `context_builder`, `provider_registry`. These are imported directly (no DI container).

## Key Patterns

- **Multi-tenancy**: All data scoped by `tenant_id`. Headers: `X-Tenant-Id`, `X-User-Id`.
- **Async everything**: async SQLAlchemy sessions, async provider calls, async event bus.
- **14 SQLAlchemy models** in `app/db/models/`, all inheriting from `Base` in `app/db/base.py`.
- **DB dependency**: `get_db()` in `app/dependencies.py` yields async sessions.
- **Static dashboard**: Legacy vanilla JS dashboard at `static/index.html`, mounted at `/static`.
- **Recordings**: Saved to `recordings/` dir, served as static files at `/recordings/`.

## Environment Variables

Configured via `pydantic-settings` in `app/config.py` (reads `.env`). Key vars: `DATABASE_URL`, `GROQ_API_KEY`, `GROQ_MODEL`, `PLIVO_AUTH_ID`/`AUTH_TOKEN`/`NUMBER`, `TWILIO_ACCOUNT_SID`/`AUTH_TOKEN`/`NUMBER`, `BASE_WEBHOOK_URL` (ngrok for webhooks), `LIVEKIT_URL`/`API_KEY`/`API_SECRET`, `SARVAM_API_KEY`.

## Deployment

- Backend: Docker (`Dockerfile` at root) with `docker-compose.yaml` for PostgreSQL + app
- For real phone calls: ngrok + webhook configuration via `scripts/setup_twilio.py` or `scripts/setup_plivo.py`
