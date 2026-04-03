"""Sarvam AI client for Indian language STT (saarika) and TTS (bulbul).

Uses a shared httpx connection pool to avoid TCP+TLS handshake overhead
on every API call (~100-300ms savings per call).
"""

import base64
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

SARVAM_BASE = "https://api.sarvam.ai"

# v2 → v3 speaker mapping (backward compat for existing tenant configs)
V2_TO_V3_SPEAKER = {"meera": "ritu", "arvind": "aditya"}

# ---------------------------------------------------------------------------
# Shared httpx connection pool — reuses TCP+TLS connections across calls
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _client


async def close_client():
    """Shut down the shared httpx client. Call from FastAPI lifespan shutdown."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


# ---------------------------------------------------------------------------
# Greeting TTS cache — avoids re-synthesizing the same greeting text
# ---------------------------------------------------------------------------

_greeting_cache: dict[str, list[bytes]] = {}


def get_cached_greeting(text: str, language: str, speaker: str) -> list[bytes] | None:
    key = f"{text[:50]}|{language}|{speaker}"
    return _greeting_cache.get(key)


def cache_greeting(text: str, language: str, speaker: str, chunks: list[bytes]) -> None:
    key = f"{text[:50]}|{language}|{speaker}"
    _greeting_cache[key] = chunks


async def transcribe(audio_data: bytes, language: str = "en") -> str:
    """Transcribe audio using the best provider per language.

    English: Groq Whisper (more accurate for telephony audio)
    Indian languages (mr, hi): Sarvam saarika (better for Indian languages)
    Each falls back to the other if unavailable.

    Args:
        audio_data: Raw audio bytes (WAV format)
        language: "en", "mr", or "hi"
    Returns:
        Transcribed text
    """
    if language in ("mr", "hi"):
        # Indian languages: Sarvam primary, Groq fallback
        if settings.sarvam_api_key:
            try:
                return await _transcribe_sarvam(audio_data, language)
            except Exception as exc:
                logger.warning("Sarvam STT failed for %s, falling back to Groq: %s", language, exc)
        if settings.groq_api_key:
            return await _transcribe_groq(audio_data, language)
    else:
        # English: Groq Whisper primary, Sarvam fallback
        if settings.groq_api_key:
            try:
                return await _transcribe_groq(audio_data, language)
            except Exception as exc:
                logger.warning("Groq STT failed, falling back to Sarvam: %s", exc)
        if settings.sarvam_api_key:
            return await _transcribe_sarvam(audio_data, language)

    raise ValueError("No STT provider configured. Set SARVAM_API_KEY or GROQ_API_KEY.")


async def _transcribe_groq(audio_data: bytes, language: str = "en") -> str:
    """Transcribe audio using Groq Whisper (whisper-large-v3-turbo)."""
    lang_code = {"en": "en", "mr": "mr", "hi": "hi"}.get(language, "en")

    client = _get_client()
    resp = await client.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        files={"file": ("audio.wav", audio_data, "audio/wav")},
        data={
            "model": "whisper-large-v3-turbo",
            "language": lang_code,
            "response_format": "json",
        },
    )
    if resp.status_code >= 400:
        logger.error("Groq STT error %d for lang=%s: %s", resp.status_code, lang_code, resp.text[:500])
    resp.raise_for_status()
    result = resp.json()
    transcript = result.get("text", "")
    logger.info("Groq STT (%s): %s", language, transcript[:100])
    return transcript


async def _transcribe_sarvam(audio_data: bytes, language: str = "en") -> str:
    """Transcribe audio using Sarvam saarika STT (fallback)."""
    if not settings.sarvam_api_key:
        raise ValueError("SARVAM_API_KEY is not configured. Cannot call Sarvam STT.")

    lang_code = {"en": "en-IN", "mr": "mr-IN", "hi": "hi-IN"}.get(language, "en-IN")

    client = _get_client()
    resp = await client.post(
        f"{SARVAM_BASE}/speech-to-text-translate",
        headers={"api-subscription-key": settings.sarvam_api_key},
        files={"file": ("audio.wav", audio_data, "audio/wav")},
        data={"model": "saaras:v3", "language_code": lang_code},
    )
    if resp.status_code >= 400:
        logger.error("Sarvam STT error %d for lang=%s: %s", resp.status_code, lang_code, resp.text[:500])
    resp.raise_for_status()
    result = resp.json()
    transcript = result.get("transcript", "")
    logger.info("Sarvam STT (%s): %s", lang_code, transcript[:100])
    return transcript


async def synthesize(
    text: str, language: str = "en", speaker: str = "ritu",
    *, temperature: float = 0.7, pace: float = 1.0,
) -> bytes:
    """Synthesize speech using Sarvam bulbul v3 TTS.

    Args:
        text: Text to speak
        language: "en", "mr", or "hi"
        speaker: v3 speaker name (ritu, aditya, priya, rahul, etc.) — also accepts v2 names (meera, arvind)
        temperature: Expressiveness (0.01-2.0, default 0.7)
        pace: Speech speed (0.5-2.0, default 1.0)
    Returns:
        Audio bytes (WAV format)
    """
    if not settings.sarvam_api_key:
        raise ValueError("SARVAM_API_KEY is not configured. Cannot call Sarvam TTS.")

    lang_code = {"en": "en-IN", "mr": "mr-IN", "hi": "hi-IN"}.get(language, "en-IN")
    speaker = V2_TO_V3_SPEAKER.get(speaker, speaker)

    client = _get_client()
    resp = await client.post(
        f"{SARVAM_BASE}/text-to-speech",
        headers={
            "api-subscription-key": settings.sarvam_api_key,
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "target_language_code": lang_code,
            "speaker": speaker,
            "model": "bulbul:v3",
            "temperature": temperature,
            "pace": pace,
        },
    )
    if resp.status_code >= 400:
        logger.error("Sarvam TTS error %d: %s", resp.status_code, resp.text[:500])
    resp.raise_for_status()
    result = resp.json()
    audio_b64 = result.get("audios", [None])[0]
    if not audio_b64:
        raise ValueError(f"No audio in Sarvam TTS response: {list(result.keys())}")
    audio_data = base64.b64decode(audio_b64)
    logger.info("Sarvam TTS (%s, %s): %d bytes", lang_code, speaker, len(audio_data))
    return audio_data


async def synthesize_stream(
    text: str, language: str = "en", speaker: str = "ritu",
    *, pace: float = 1.0,
):
    """Stream TTS audio as raw mulaw bytes via Sarvam HTTP streaming API.

    Yields mulaw audio chunks as they arrive — first chunk in ~500ms
    instead of waiting 5-9s for the full response. Output is raw 8kHz
    mulaw ready for Plivo playback (no WAV conversion needed).
    """
    if not settings.sarvam_api_key:
        raise ValueError("SARVAM_API_KEY is not configured. Cannot call Sarvam TTS.")

    lang_code = {"en": "en-IN", "mr": "mr-IN", "hi": "hi-IN"}.get(language, "en-IN")
    speaker = V2_TO_V3_SPEAKER.get(speaker, speaker)

    client = _get_client()
    async with client.stream(
        "POST",
        f"{SARVAM_BASE}/text-to-speech/stream",
        headers={
            "api-subscription-key": settings.sarvam_api_key,
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "target_language_code": lang_code,
            "speaker": speaker,
            "model": "bulbul:v3",
            "output_audio_codec": "mulaw",
            "speech_sample_rate": 8000,
            "pace": pace,
        },
    ) as resp:
        if resp.status_code >= 400:
            body = await resp.aread()
            logger.error("Sarvam TTS stream error %d: %s", resp.status_code, body[:500])
            resp.raise_for_status()
        total = 0
        async for chunk in resp.aiter_bytes(chunk_size=640):
            total += len(chunk)
            yield chunk
        logger.info("Sarvam TTS stream (%s, %s): %d bytes total", lang_code, speaker, total)
