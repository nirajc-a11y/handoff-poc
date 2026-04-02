from contextlib import asynccontextmanager
import logging
import os

# Ensure application logs are visible in the terminal
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.events import event_bus
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
    # Startup: wire broadcaster to event bus
    broadcaster = WSBroadcaster(event_bus, ws_manager)
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

    yield
    # Shutdown
    from app.voice_ai import sarvam
    await sarvam.close_client()
    await engine.dispose()


app = FastAPI(
    title="Handoff POC",
    description="Multi-tenant telecom handoff orchestration engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/recordings", StaticFiles(directory=_recordings_dir), name="recordings")

from app.api.v1.router import v1_router  # noqa: E402

app.include_router(v1_router, prefix="/api/v1")
