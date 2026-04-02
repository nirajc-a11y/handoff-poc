"""Sarvam AI client for Indian language STT (saarika) and TTS (bulbul)."""

import base64
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

SARVAM_BASE = "https://api.sarvam.ai"


async def transcribe(audio_data: bytes, language: str = "en") -> str:
    """Transcribe audio using Sarvam saarika STT.

    Args:
        audio_data: Raw audio bytes (WAV format)
        language: "en", "mr", or "hi"
    Returns:
        Transcribed text
    """
    lang_code = {"en": "en-IN", "mr": "mr-IN", "hi": "hi-IN"}.get(language, "en-IN")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{SARVAM_BASE}/speech-to-text-translate",
            headers={"api-subscription-key": settings.sarvam_api_key},
            files={"file": ("audio.wav", audio_data, "audio/wav")},
            data={"model": "saarika:v2", "language_code": lang_code},
        )
        resp.raise_for_status()
        result = resp.json()
        transcript = result.get("transcript", "")
        logger.info("Sarvam STT (%s): %s", lang_code, transcript[:100])
        return transcript


async def synthesize(text: str, language: str = "en", speaker: str = "meera") -> bytes:
    """Synthesize speech using Sarvam bulbul TTS.

    Args:
        text: Text to speak
        language: "en", "mr", or "hi"
        speaker: "meera" (female) or "arvind" (male)
    Returns:
        Audio bytes (WAV format)
    """
    lang_code = {"en": "en-IN", "mr": "mr-IN", "hi": "hi-IN"}.get(language, "en-IN")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{SARVAM_BASE}/text-to-speech",
            headers={
                "api-subscription-key": settings.sarvam_api_key,
                "Content-Type": "application/json",
            },
            json={
                "inputs": [text],
                "target_language_code": lang_code,
                "speaker": speaker,
                "model": "bulbul:v2",
                "enable_preprocessing": True,
            },
        )
        resp.raise_for_status()
        result = resp.json()
        audio_b64 = result.get("audios", [None])[0]
        if not audio_b64:
            raise ValueError("No audio in Sarvam TTS response")
        audio_data = base64.b64decode(audio_b64)
        logger.info("Sarvam TTS (%s, %s): %d bytes", lang_code, speaker, len(audio_data))
        return audio_data
