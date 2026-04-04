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

`dev.sh` orchestrates: Docker PostgreSQL + Redis + LiveKit -> ngrok (auto-detects static domain from `.env`) -> updates `BASE_WEBHOOK_URL` in `.env` -> updates Plivo app webhooks via API -> uvicorn `:8000` -> pnpm dev `:5173`. Ctrl+C stops all.

### Backend (project root)
```bash
docker compose up -d postgres redis     # Start PostgreSQL + Redis
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
5. Publishes to the Redis-backed async event bus

### State Machine (`app/core/state_machine.py`)
11 states, 24 triggers. Pure function: `transition(state, trigger) -> (new_state, event_type)`. No side effects — the transition table is a dict mapping `(ConversationState, Trigger)` tuples.

States: `INITIATED -> RINGING -> IVR -> AI_HANDLING -> QUEUED_FOR_HUMAN -> HUMAN_HANDLING -> WRAP_UP -> ENDED` (plus `ON_HOLD`, `TRANSFERRED`, `FAILED`).

### Event Bus (`app/core/events.py`) + Redis Pub/Sub

Events are published to Redis channels via `event_bus.publish(event)`. The `WSBroadcaster` (`app/ws/broadcaster.py`) runs a background task that `psubscribe`s to Redis patterns (`conversation.*`, `agent.*`, `queue.*`, etc.) and relays events to tenant-scoped WebSocket clients. Redis connection pool is managed by `app/core/redis.py` (lazy-initialised singleton). Module-level singleton: `event_bus`.

### Provider Architecture (`app/providers/`)
Pluggable ABC interfaces for 4 channels: `TelephonyProvider`, `WhatsAppProvider`, `EmailProvider`, `SMSProvider` (defined in `base.py`). The `ProviderRegistry` resolves per-tenant provider from tenant config JSONB (`{"providers": {"telephony": "twilio"}}`). Falls back to mock providers automatically.

Implementations: Twilio, Plivo (voice only), Mock (all channels). Providers are registered at startup in `app/main.py` lifespan based on env var presence.

### Real-time Voice AI (`app/voice_ai/voice_agent.py`)

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

### LiveKit Agent Mode (feature-flagged)

When `USE_LIVEKIT_AGENT=true`, the voice pipeline switches from the custom VoiceAISession to a LiveKit-based architecture:

- **Plivo-LiveKit Bridge** (`app/voice_ai/plivo_livekit_bridge.py`): Receives mulaw audio from Plivo WebSocket, converts to PCM, publishes as a LiveKit audio track. Subscribes to the Agent's audio track and sends PCM→mulaw back to Plivo. Streams a cached TTS greeting immediately on connect (before the agent joins the room).
- **LiveKit Agent Worker** (`app/voice_ai/livekit_agent.py`): Standalone worker process using LiveKit Agents SDK. Auto-joins rooms and runs the STT→LLM→TTS pipeline. Uses **Deepgram STT (nova-3)**, **Silero VAD**, **Groq LLM** (direct, not via SarvamLLM plugin), and language-aware TTS (Deepgram Aura 2 for English, Sarvam Bulbul v3 for Marathi). Tool-based call control (`end_call`, `transfer_to_human` functions) replaces keyword matching. Run separately: `python -m app.voice_ai.livekit_agent`.
- **SarvamLLM Plugin** (`app/voice_ai/sarvam_llm_plugin.py`): LiveKit-compatible LLM plugin wrapping AIEngine — kept for reference but agent now calls Groq directly.
- **SarvamTTS Plugin** (`app/voice_ai/sarvam_tts_plugin.py`): LiveKit-compatible TTS plugin wrapping Sarvam Bulbul v3. Converts mulaw→PCM for LiveKit transport.
- **Sample Reference** (`app/voice_ai/sample_file.py`): Example implementation for claim verification calls — useful as a template for new LiveKit agent use-cases.

The feature flag is in `app/config.py` (`use_livekit_agent`). When disabled, the legacy VoiceAISession path is used unchanged.

### Transcript Persistence (Redis pub/sub)

LiveKit agent worker has no DB connection. Transcripts flow via Redis:

1. `livekit_agent.py` publishes `{"type": "transcript", "sender_type": "ai|customer", "content": "..."}` to Redis channel `transcript.added`
2. `app/services/transcript_handler.py` runs as a background task in the FastAPI main process, subscribed to `transcript.added`
3. Handler saves `Message` records to DB, then publishes `conversation.message_added` event to the event bus
4. Avoids the DB connection bottleneck that would occur if the worker process held async sessions

### Room Pre-warming (`app/services/room_prewarmer.py`)

Eliminates the ~2.74s LiveKit dispatch delay when AI handling begins:

- During IVR navigation (typically 10-20s), a LiveKit room is pre-created for the conversation
- When DTMF triggers AI dispatch, the room is already available — agent connects immediately
- `room_prewarmer.py` manages a pool of pre-warmed rooms keyed by `conversation_id`
- A periodic cleanup task in `app/main.py` lifespan reclaims stale rooms

### Supervisor Subsystem

Live call supervision with Listen, Whisper, and Barge modes:

- **Session Registry** (`app/voice_ai/session_registry.py`): Module-level dict tracking active `VoiceAISession` instances by `conversation_id`. Stores session, Plivo WebSocket, stream_sid, and listener queues. Registered/unregistered in `plivo_stream.py`.
- **Listen** (`WS /api/v1/supervisor/listen/{conv_id}`): Forwards a copy of caller + AI audio to supervisor browser via WebSocket. Frontend decodes mulaw and plays via Web Audio API.
- **Whisper** (`POST /api/v1/supervisor/whisper/{conv_id}`): Injects supervisor guidance as a system message into `conversation_history`. AI incorporates it in the next response. Customer never hears it.
- **Barge** (`POST /api/v1/supervisor/barge/{conv_id}`): Cancels AI pipeline (`_barge_in_event`), sends `clearAudio`, transitions to `QUEUED_FOR_HUMAN`, redirects Plivo call to conference room. Supervisor joins via browser softphone.

When LiveKit agent mode is enabled, supervisor uses LiveKit-native endpoints instead:

- **LiveKit Token** (`POST /api/v1/supervisor/livekit-token/{conv_id}`): Generates a LiveKit room token (listen-only or publish-enabled for barge).
- **LiveKit Whisper** (`POST /api/v1/supervisor/livekit-whisper/{conv_id}`): Sends whisper hints via LiveKit data channel; the agent injects them as system context.
- **LiveKit Barge** (`POST /api/v1/supervisor/livekit-barge/{conv_id}`): Sends barge signal via data channel, mutes AI agent, transitions state to `HUMAN_HANDLING`, returns publish-enabled room token.
- The frontend (`use-supervisor.ts`) tries LiveKit endpoints first and falls back to legacy WebSocket automatically.

### API Layer
All routes under `/api/v1/` via `app/api/v1/router.py`. 91+ endpoints. Swagger at `/docs`. Multi-tenancy enforced via `X-Tenant-Id` header (see `app/dependencies.py`).

### Frontend
React 19 + Vite + TailwindCSS v4. Path alias `@/` maps to `./src/`. Pages: live dashboard, agents, campaigns, analytics, IVR config, history, settings. Browser softphone (Plivo WebRTC) in right panel. Supervisor panel in conversation detail (Listen/Whisper/Barge controls). State via Jotai atoms (`src/stores/`), data fetching via TanStack React Query. Vite proxies `/api`, `/ws`, `/recordings` to backend at `:8000`.

**Notable frontend additions:**

- `src/components/error-boundary.tsx` + `src/stores/errors.ts` — top-level error boundary with error state atom
- `src/components/layout/offline-indicator.tsx` — connectivity banner, shown when WebSocket drops
- Skeleton loaders in `src/components/live/` for async conversation list + detail states
- `src/hooks/use-websocket.ts` — WebSocket hook with automatic reconnection logic
- `src/hooks/use-livekit-agent.ts` — LiveKit agent connection hook for supervisor panel
- `src/hooks/use-supervisor.ts` — tries LiveKit endpoints first, falls back to legacy WebSocket

### Module-Level Singletons
Core engines are instantiated as module-level singletons at the bottom of their files: `handoff_engine`, `event_bus`, `routing_engine`, `ai_engine`, `ivr_engine`, `context_builder`, `provider_registry`, `room_prewarmer`. These are imported directly (no DI container).

## Key Patterns

- **Multi-tenancy**: All data scoped by `tenant_id`. Headers: `X-Tenant-Id`, `X-User-Id`.
- **Async everything**: async SQLAlchemy sessions, async provider calls, Redis pub/sub event bus.
- **14 SQLAlchemy models** in `app/db/models/`, all inheriting from `Base` in `app/db/base.py`.
- **DB dependency**: `get_db()` in `app/dependencies.py` yields async sessions.
- **Static dashboard**: Legacy vanilla JS dashboard at `static/index.html`, mounted at `/static`.
- **Recordings**: Saved to `recordings/` dir, served as static files at `/recordings/`.

## Environment Variables

Configured via `pydantic-settings` in `app/config.py` (reads `.env`). `app/config.py` runs `validate_on_startup()` in the FastAPI lifespan — fails fast on fatal misconfig (`DATABASE_URL`, `REDIS_URL`, LiveKit consistency) and logs warnings for missing optional providers.

**Core:** `DATABASE_URL`, `REDIS_URL`

**LLM:** `GROQ_API_KEY`, `GROQ_MODEL` (default: `meta-llama/llama-4-scout-17b-16e-instruct`)

**Telephony:** `PLIVO_AUTH_ID`/`PLIVO_AUTH_TOKEN`/`PLIVO_NUMBER`, `TWILIO_ACCOUNT_SID`/`AUTH_TOKEN`/`NUMBER`, `BASE_WEBHOOK_URL` (ngrok URL for provider callbacks)

**LiveKit:** `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`, `USE_LIVEKIT_AGENT` (default: `false`)

**Speech:** `SARVAM_API_KEY` (STT + Marathi TTS), `DEEPGRAM_API_KEY` (STT + English TTS)

**Voice pipeline tuning (all have defaults):** `VAD_THRESHOLD`, `VAD_ENDPOINTING_PROFILE`, `DEEPGRAM_STT_MODEL`, `DEEPGRAM_TTS_MODEL`, `DEEPGRAM_ENDPOINTING_MS`, `SARVAM_TTS_SPEAKER`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_TOKENS`, `BARGEIN_MIN_DURATION`, `GREETING_CACHE_TIMEOUT`, `QUEUE_TIMEOUT_SECONDS`

## Scripts

| Script | Purpose |
| ------ | ------- |
| `scripts/dev.sh` | Start full stack (postgres + ngrok + backend + frontend) |
| `scripts/seed.py` | Seed demo tenant, agents, IVR, campaign, leads |
| `scripts/seed_vsynergize.py` | Seed VSynergize tenant for Plivo integration testing |
| `scripts/demo.py` | Run all 6 handoff scenarios (mock, no provider needed) |
| `scripts/setup_twilio.py` | Configure Twilio webhooks |
| `scripts/setup_plivo.py` | Create Plivo app + endpoints |
| `scripts/setup_plivo_vsynergize.py` | Configure VSynergize Plivo endpoints |
| `scripts/setup_inbound.py` | Setup inbound phone number |
| `scripts/update_webhooks.py` | Sync Plivo webhook URLs from `BASE_WEBHOOK_URL` |
| `scripts/verify_number.py` | Verify Plivo caller IDs |
| `scripts/docker-entrypoint.sh` | Docker entrypoint (runs Alembic migrations then starts server) |

## Deployment

- Backend: Docker (`Dockerfile` at root) with `docker-compose.yaml` for PostgreSQL + Redis + LiveKit + app. `scripts/docker-entrypoint.sh` runs `alembic upgrade head` before starting uvicorn.
- Railway: `Dockerfile.railway` + `railway.toml` for Railway.app deployment
- For real phone calls: ngrok + webhook configuration via `scripts/setup_twilio.py` or `scripts/setup_plivo.py`
