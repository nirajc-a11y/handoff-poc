from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/handoff_poc"
    groq_api_key: str = ""
    groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # Sarvam LLM (Sarvam 30B — multilingual, optimized for Indian languages)
    sarvam_llm_model: str = "sarvam-m"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Plivo telephony provider
    plivo_auth_id: str = ""
    plivo_auth_token: str = ""
    plivo_number: str = ""  # The Plivo phone number (e.g. "+14155551234")
    base_webhook_url: str = "http://localhost:8000"  # ngrok URL for production

    # Twilio telephony provider
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_number: str = ""  # The Twilio phone number (e.g. "+14155551234")

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LiveKit
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    use_livekit_agent: bool = True

    # Sarvam AI (Indian language STT/TTS)
    sarvam_api_key: str = ""

    # Deepgram (streaming STT)
    deepgram_api_key: str = ""

    # ElevenLabs (TTS — high quality, low latency)
    elevenlabs_api_key: str = ""

    # Voice Activity Detection (Silero VAD)
    vad_threshold: float = 0.5
    vad_endpointing_profile: str = "ai_conversation"

    # Bridge audio
    bridge_silence_threshold: int = 50

    # Voice pipeline tuning
    deepgram_stt_model: str = "nova-3"
    deepgram_tts_model: str = "aura-2-asteria-en"  # warmer voice, better clarity at 8kHz telephony
    deepgram_endpointing_ms: int = 150  # ms of silence before Deepgram finalises transcript
    sarvam_tts_speaker: str = "ritu"
    llm_timeout_seconds: float = 8.0
    llm_max_tokens: int = 120  # one short sentence fits in ~60-80 tokens; hard cap keeps responses brief
    vad_min_silence_duration: float = 0.15  # trigger turn end faster after caller stops speaking
    vad_activation_threshold: float = 0.45
    bargein_min_duration: float = 0.15
    greeting_cache_timeout: float = 300.0
    plivo_send_max_retries: int = 3
    circuit_breaker_threshold: int = 3
    queue_timeout_seconds: int = 300

    # Filler audio played while AI pipeline connects (eliminates dead air)
    plivo_filler_audio_url: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def validate_voice_pipeline(self) -> list[str]:
        """Check voice pipeline config. Returns warnings. Raises on fatal."""
        warnings: list[str] = []

        if self.use_livekit_agent:
            if not self.livekit_url:
                raise ValueError("use_livekit_agent=True but LIVEKIT_URL is empty")
            if not self.livekit_api_key or not self.livekit_api_secret:
                raise ValueError("use_livekit_agent=True but LIVEKIT_API_KEY/SECRET missing")
            if not self.deepgram_api_key:
                raise ValueError("LiveKit agent requires DEEPGRAM_API_KEY for STT")
            if not self.sarvam_api_key:
                raise ValueError("LiveKit agent requires SARVAM_API_KEY for TTS")

        if not self.sarvam_api_key and not self.groq_api_key:
            warnings.append("No LLM provider configured (SARVAM_API_KEY, GROQ_API_KEY)")

        if not self.plivo_auth_id and not self.twilio_account_sid:
            warnings.append("No telephony provider configured (Plivo or Twilio)")

        return warnings

    def validate_on_startup(self) -> None:
        """Called during FastAPI lifespan — raises on critical misconfig."""
        import logging
        _log = logging.getLogger(__name__)

        # Fatal checks
        warnings = self.validate_voice_pipeline()
        for w in warnings:
            _log.warning("CONFIG: %s", w)

        if not self.database_url:
            raise ValueError("DATABASE_URL is required")

        if not self.redis_url:
            raise ValueError("REDIS_URL is required")

        if self.use_livekit_agent:
            if not self.groq_api_key:
                _log.warning("CONFIG: GROQ_API_KEY missing — LLM will fall back to Sarvam or mock")
            if not self.base_webhook_url or "localhost" in self.base_webhook_url:
                _log.warning("CONFIG: BASE_WEBHOOK_URL is localhost — Plivo webhooks won't work")


settings = Settings()
