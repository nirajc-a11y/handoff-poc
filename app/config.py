from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/handoff_poc"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
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

    # LiveKit (unused — kept so .env values don't break pydantic-settings)
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Sarvam AI (Indian language STT/TTS)
    sarvam_api_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
