"""Health check endpoints for orchestration and monitoring."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness check — is the process running?"""
    return {"status": "ok"}


@router.get("/ready")
async def ready(db: AsyncSession = Depends(get_db)) -> dict:
    """Readiness check — can the app serve requests?

    Checks: database, Redis, and LiveKit (if enabled).
    Returns 503 if any dependency is unhealthy.
    """
    checks: dict[str, str] = {}
    healthy = True

    # Database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        healthy = False

    # Redis
    try:
        from app.core.redis import get_redis
        redis = get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        healthy = False

    # LiveKit (if enabled)
    if settings.use_livekit_agent and settings.livekit_url:
        try:
            from livekit import api as lk_api
            lk = lk_api.LiveKitAPI(
                url=settings.livekit_url,
                api_key=settings.livekit_api_key,
                api_secret=settings.livekit_api_secret,
            )
            try:
                await lk.room.list_rooms(lk_api.ListRoomsRequest())
                checks["livekit"] = "ok"
            finally:
                await lk.aclose()
        except Exception as e:
            checks["livekit"] = f"error: {e}"
            healthy = False

    status_code = 200 if healthy else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"status": "ready" if healthy else "unhealthy", "checks": checks},
        status_code=status_code,
    )
