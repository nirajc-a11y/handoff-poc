from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/handoff_poc"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

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
    use_livekit_agent: bool = False

    # Sarvam AI (Indian language STT/TTS)
    sarvam_api_key: str = ""

    # Deepgram (streaming STT)
    deepgram_api_key: str = ""

    # Voice Activity Detection (Silero VAD)
    vad_threshold: float = 0.5
    vad_endpointing_profile: str = "ai_conversation"

    # Bridge audio
    bridge_silence_threshold: int = 50
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
                raise ValueError("LiveKit agent requires DEEPGRAM_API_KEY for STT/TTS")

        if not self.sarvam_api_key and not self.groq_api_key:
            warnings.append("No LLM provider configured (SARVAM_API_KEY, GROQ_API_KEY)")

        if not self.sarvam_api_key:
            warnings.append("SARVAM_API_KEY missing — TTS will not work")

        if not self.plivo_auth_id and not self.twilio_account_sid:
            warnings.append("No telephony provider configured (Plivo or Twilio)")

        return warnings


settings = Settings()
