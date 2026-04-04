from contextlib import asynccontextmanager
import asyncio
import logging
import os
import warnings

# Suppress pydantic "model_" namespace warnings from livekit-agents internals
warnings.filterwarnings("ignore", message=".*Field.*model_.*protected namespace.*")

# Structured log format with correlation ID
from app.middleware.correlation import CorrelationIdFilter

_log_handler = logging.StreamHandler()
_log_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s [%(name)s] [%(correlation_id)s] %(message)s")
)
_log_handler.addFilter(CorrelationIdFilter())
logging.root.addHandler(_log_handler)
logging.root.setLevel(logging.INFO)


from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.core.redis import close_redis
from app.db.engine import engine
from app.providers.registry import provider_registry
from app.ws.broadcaster import WSBroadcaster
from app.ws.manager import ws_manager

logger = logging.getLogger(__name__)

# Ensure the recordings directory exists
_recordings_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "recordings")
os.makedirs(_recordings_dir, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate all config (fail fast on fatal misconfig)
    try:
        settings.validate_on_startup()
    except ValueError as exc:
        logger.error("FATAL config error: %s", exc)
        raise SystemExit(1) from exc

    # Startup: wire broadcaster to Redis pub/sub -> WebSocket
    broadcaster = WSBroadcaster(ws_manager)
    broadcaster.start()

    # Register Plivo provider if credentials are configured
    if settings.plivo_auth_id:
        from app.providers.plivo.telephony import PlivoTelephonyProvider

        plivo_provider = PlivoTelephonyProvider(
            auth_id=settings.plivo_auth_id,
            auth_token=settings.plivo_auth_token,
            base_webhook_url=settings.base_webhook_url,
        )
        provider_registry.register("telephony", "plivo", plivo_provider)
        logger.info("Plivo telephony provider registered")

    # Register Twilio provider if credentials are configured
    if settings.twilio_account_sid:
        from app.providers.twilio.telephony import TwilioTelephonyProvider

        twilio_provider = TwilioTelephonyProvider(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            base_webhook_url=settings.base_webhook_url,
        )
        provider_registry.register("telephony", "twilio", twilio_provider)
        logger.info("Twilio telephony provider registered")

    # Pre-load Silero VAD ONNX model so first call has no cold-start delay
    from app.voice_ai.vad import _get_model_path
    _get_model_path()
    logger.info("Silero VAD model pre-loaded")

    # Log LiveKit agent status
    if settings.use_livekit_agent and settings.livekit_url:
        logger.info(
            "LiveKit agent mode enabled — run the agent worker separately with: "
            "python -m app.voice_ai.livekit_agent"
        )

    # Start periodic cleanup of stale pre-warmed LiveKit rooms
    _room_cleanup_task = None
    if settings.use_livekit_agent and settings.livekit_url:
        async def _periodic_room_cleanup():
            from app.services.room_prewarmer import room_prewarmer
            while True:
                try:
                    await asyncio.sleep(30)
                    await room_prewarmer.cleanup_stale(max_age_seconds=60)
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.warning("Room cleanup error", exc_info=True)

        _room_cleanup_task = asyncio.create_task(_periodic_room_cleanup())

    # Start queue timeout monitor
    from app.services.queue_monitor import run_queue_monitor
    _queue_monitor_task = asyncio.create_task(run_queue_monitor())

    yield
    # Shutdown — try/finally ensures all cleanup runs even if one step fails
    if _room_cleanup_task and not _room_cleanup_task.done():
        _room_cleanup_task.cancel()
        try:
            await _room_cleanup_task
        except asyncio.CancelledError:
            pass
    if _queue_monitor_task and not _queue_monitor_task.done():
        _queue_monitor_task.cancel()
        try:
            await _queue_monitor_task
        except asyncio.CancelledError:
            pass
    try:
        await broadcaster.stop()
    except Exception:
        logger.exception("Error stopping broadcaster")
    try:
        from app.voice_ai import sarvam
        await sarvam.close_client()
    except Exception:
        logger.exception("Error closing Sarvam client")
    try:
        await close_redis()
    except Exception:
        logger.exception("Error closing Redis")
    try:
        await engine.dispose()
    except Exception:
        logger.exception("Error disposing DB engine")


app = FastAPI(
    title="Handoff POC",
    description="Multi-tenant telecom handoff orchestration engine",
    version="0.1.0",
    lifespan=lifespan,
)

from app.middleware.correlation import CorrelationIdMiddleware
app.add_middleware(CorrelationIdMiddleware)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/recordings", StaticFiles(directory=_recordings_dir), name="recordings")

from app.api.v1.router import v1_router  # noqa: E402

app.include_router(v1_router, prefix="/api/v1")

# Expose health endpoints at root (without /api/v1 prefix) for load balancers
from app.api.v1.health import router as health_router  # noqa: E402
app.include_router(health_router)

# Serve frontend SPA build (Railway / production)
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend_dist"
if _frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_frontend_dist / "assets"), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Catch-all: serve index.html for client-side routing."""
        file = _frontend_dist / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(_frontend_dist / "index.html")
