"""Sarvam AI client for Indian language STT (saarika) and TTS (bulbul)."""

import base64
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

SARVAM_BASE = "https://api.sarvam.ai"

# v2 → v3 speaker mapping (backward compat for existing tenant configs)
V2_TO_V3_SPEAKER = {"meera": "ritu", "arvind": "aditya"}


async def transcribe(audio_data: bytes, language: str = "en") -> str:
    """Transcribe audio using Sarvam saarika STT.

    Args:
        audio_data: Raw audio bytes (WAV format)
        language: "en", "mr", or "hi"
    Returns:
        Transcribed text
    """
    if not settings.sarvam_api_key:
        raise ValueError("SARVAM_API_KEY is not configured. Cannot call Sarvam STT.")

    lang_code = {"en": "en-IN", "mr": "mr-IN", "hi": "hi-IN"}.get(language, "en-IN")

    async with httpx.AsyncClient(timeout=30.0) as client:
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

    async with httpx.AsyncClient(timeout=30.0) as client:
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
