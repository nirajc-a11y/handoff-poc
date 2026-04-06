"""Redis-backed greeting TTS cache.

Pre-synthesizes and caches greeting audio per tenant+language+speaker.
Called during IVR phase so the greeting is ready before DTMF arrives.
Cache hit = 0ms TTS latency vs ~1.08s live Sarvam synthesis.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

GREETING_TEMPLATES = {
    "en": "Welcome to {company_name}. I'm your AI assistant. How can I help you today?",
    "hi": "नमस्ते! {company_name} में आपका स्वागत है। मैं आपकी AI ��हायक हूँ। मैं आपकी कैसे मदद कर सकती हूँ?",
    "mr": "{company_name} विक्री विभागात आपले स्वागत आहे. मी तुमचा AI सहाय्यक आहे. मी तुम्हाला कशी मदत करू शकतो?",
}

_CACHE_TTL = int(settings.greeting_cache_timeout)


def _cache_key(tenant_id: str, language: str, company_name: str) -> str:
    """Deterministic key: greeting:{tenant}:{lang}:{content_hash}."""
    content = GREETING_TEMPLATES.get(language, GREETING_TEMPLATES["en"]).format(
        company_name=company_name
    )
    content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"greeting:{tenant_id}:{language}:{content_hash}"


async def get_cached_greeting(
    redis: aioredis.Redis,
    tenant_id: str,
    language: str,
    company_name: str,
) -> Optional[bytes]:
    """Fetch pre-synthesized mulaw greeting audio from Redis."""
    key = _cache_key(tenant_id, language, company_name)
    try:
        # Use a separate non-decode connection for binary data
        raw_redis = aioredis.from_url(
            settings.redis_url, decode_responses=False, max_connections=5,
        )
        try:
            data = await raw_redis.get(key)
        finally:
            await raw_redis.aclose()
        if data:
            logger.info("Greeting cache HIT (tenant=%s, lang=%s, %d bytes)", tenant_id, language, len(data))
            return data
        logger.info("Greeting cache MISS (tenant=%s, lang=%s)", tenant_id, language)
        return None
    except Exception:
        logger.warning("Greeting cache read error", exc_info=True)
        return None


async def cache_greeting(
    redis: aioredis.Redis,
    tenant_id: str,
    language: str,
    company_name: str,
    audio_bytes: bytes,
) -> None:
    """Store synthesized greeting in Redis. TTL from settings.greeting_cache_timeout."""
    key = _cache_key(tenant_id, language, company_name)
    try:
        raw_redis = aioredis.from_url(
            settings.redis_url, decode_responses=False, max_connections=5,
        )
        try:
            await raw_redis.set(key, audio_bytes, ex=_CACHE_TTL)
        finally:
            await raw_redis.aclose()
        logger.info("Greeting cached (key=%s, size=%d bytes)", key, len(audio_bytes))
    except Exception:
        logger.warning("Greeting cache write error", exc_info=True)


async def warm_greeting_cache(
    tenant_id: str,
    language: str,
    company_name: str,
    speaker: str = "ritu",
) -> None:
    """Background task: synthesize greeting and cache it.

    Called during IVR phase so it's ready before DTMF arrives.
    """
    from app.core.redis import get_redis
    from app.voice_ai import sarvam

    redis = get_redis()

    # Check if already cached
    existing = await get_cached_greeting(redis, tenant_id, language, company_name)
    if existing:
        return

    text = GREETING_TEMPLATES.get(language, GREETING_TEMPLATES["en"]).format(
        company_name=company_name
    )
    try:
        # Synthesize as streaming mulaw and collect all chunks
        chunks: list[bytes] = []
        async for chunk in sarvam.synthesize_stream(text, language, speaker):
            chunks.append(chunk)
        if chunks:
            full_audio = b"".join(chunks)
            await cache_greeting(redis, tenant_id, language, company_name, full_audio)
            logger.info("Greeting warmed (tenant=%s, lang=%s, %d bytes)", tenant_id, language, len(full_audio))
    except Exception:
        logger.warning("Greeting cache warm failed (non-fatal)", exc_info=True)
