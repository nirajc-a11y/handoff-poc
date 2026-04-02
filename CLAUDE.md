# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Handoff POC is a multi-tenant telecom handoff orchestration engine. It demonstrates real-time IVR / AI / Human agent handoffs across Voice, WhatsApp, Email, and SMS channels with a live operations dashboard.

Two independent sub-projects:
- **Backend** (root `app/`) — Python FastAPI with async SQLAlchemy, Alembic migrations
- **Frontend** (`frontend/`) — React 19 SPA with Vite, TailwindCSS v4, shadcn/ui

## Development Commands

### Backend (project root)
```bash
docker compose up -d postgres          # Start PostgreSQL
pip install -e .                        # Install dependencies (editable)
pip install -e ".[dev]"                 # Include dev deps (pytest, pytest-asyncio)
python -m scripts.seed                  # Seed demo data (tenant, agents, IVR, campaign, leads)
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000  # Dev server
python -m scripts.demo --tenant-id <ID> # Run all 6 handoff scenarios (mock, no provider needed)
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
Pipeline: Plivo audio stream (mulaw 8kHz) -> Sarvam STT -> Groq LLM (Llama 3) -> Sarvam TTS -> mulaw playback. Silence detection triggers turn processing. Bilingual: English + Marathi.

### API Layer
All routes under `/api/v1/` via `app/api/v1/router.py`. 87+ endpoints. Swagger at `/docs`. Multi-tenancy enforced via `X-Tenant-Id` header (see `app/dependencies.py`).

### Frontend
React 19 + Vite + TailwindCSS v4. Path alias `@/` maps to `./src/`. Pages: live dashboard, agents, campaigns, analytics, IVR config, history, settings. Also has a browser softphone component (Plivo WebRTC). State via Jotai atoms (`src/stores/`), data fetching via TanStack React Query. Vite proxies `/api`, `/ws`, `/recordings` to backend at `:8000`.

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

Configured via `pydantic-settings` in `app/config.py` (reads `.env`). Key vars: `DATABASE_URL`, `GROQ_API_KEY`, `TWILIO_ACCOUNT_SID`/`AUTH_TOKEN`/`NUMBER`, `PLIVO_AUTH_ID`/`AUTH_TOKEN`/`NUMBER`, `BASE_WEBHOOK_URL` (ngrok for webhooks), `LIVEKIT_URL`/`API_KEY`/`API_SECRET`, `SARVAM_API_KEY`.

## Deployment

- Backend: Docker (`Dockerfile` at root) with `docker-compose.yaml` for PostgreSQL + app
- For real phone calls: ngrok + webhook configuration via `scripts/setup_twilio.py` or `scripts/setup_plivo.py`
