"""LiveKit Voice AI Agent — replaces the custom VoiceAISession.

Uses LiveKit's Agent + AgentSession with:
  - STT: Deepgram (streaming, via livekit-plugins-deepgram)
  - VAD: Silero (built-in, via livekit-plugins-silero)
  - LLM: SarvamLLM plugin (wraps existing Groq/Sarvam engine)
  - TTS: Deepgram Aura (fast, low-latency)
"""

from __future__ import annotations

import json
import logging
import warnings

# Suppress pydantic "model_" namespace warnings from livekit-agents internals
warnings.filterwarnings("ignore", message=".*Field.*model_.*protected namespace.*")

from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
)
from livekit.plugins import deepgram, silero

from app.voice_ai.sarvam_llm_plugin import SarvamLLM

logger = logging.getLogger(__name__)


def prewarm(proc: JobProcess) -> None:
    """Pre-load the Silero VAD model so first call has no cold-start."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    """Main agent entrypoint — called once per LiveKit room."""
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Extract configuration from room metadata
    metadata = {}
    if ctx.room.metadata:
        try:
            metadata = json.loads(ctx.room.metadata)
        except json.JSONDecodeError:
            logger.warning("Failed to parse room metadata: %s", ctx.room.metadata)

    language = metadata.get("language", "en")
    company_name = metadata.get("company_name", "Demo Corp")
    tenant_id = metadata.get("tenant_id", "")
    conversation_id = metadata.get("conversation_id", "")

    logger.info(
        "LiveKit agent joining room %s (tenant=%s, conv=%s, lang=%s)",
        ctx.room.name, tenant_id, conversation_id, language,
    )

    from app.config import settings as _settings

    # VAD from prewarm or load fresh
    vad = ctx.proc.userdata.get("vad") or silero.VAD.load()

    # LLM plugin (with escalation/end-call detection)
    llm_plugin = SarvamLLM(language=language, company_name=company_name)

    # Deepgram TTS — fast, low-latency, no Sarvam HTTP roundtrip
    tts_plugin = deepgram.TTS(
        api_key=_settings.deepgram_api_key,
        model="aura-2-andromeda-en",
    )

    # Deepgram STT
    stt_plugin = deepgram.STT(
        api_key=_settings.deepgram_api_key,
        language=_deepgram_lang(language),
        model="nova-2",
    )

    # Create agent
    agent = Agent(
        instructions=_get_instructions(language, company_name),
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
        vad=vad,
    )

    # Handle data messages from supervisor (whisper / barge)
    @ctx.room.on("data_received")
    def _on_data(data: bytes, *, participant=None, kind=None, topic=None, **kwargs) -> None:
        try:
            msg = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        msg_type = msg.get("type")
        if msg_type == "whisper":
            llm_plugin.inject_system_hint(msg.get("message", ""))
            logger.info("Supervisor whisper received for room %s", ctx.room.name)
        elif msg_type == "barge":
            logger.info("Supervisor barge received for room %s", ctx.room.name)

    # Start the session — greeting is already played by the Plivo bridge
    session = AgentSession(
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
        vad=vad,
    )

    await session.start(agent, room=ctx.room)
    logger.info("LiveKit agent started in room %s", ctx.room.name)


def _deepgram_lang(language: str) -> str:
    return {"en": "en-US", "hi": "hi", "mr": "mr"}.get(language, "en-US")


def _get_instructions(language: str, company_name: str) -> str:
    if language == "mr":
        return (
            f"तुम्ही {company_name} च्या व्यावसायिक ग्राहक सेवा एजंट आहात. तुमचे नाव माया आहे. "
            "उत्तरे लहान ठेवा — जास्तीत जास्त 1 ते 3 वाक्ये. पूर्णपणे मराठीत उत्तर द्या."
        )
    return (
        f"You are a professional customer support agent for {company_name}. "
        "Your name is Maya. Keep responses SHORT — 1 to 3 sentences maximum. "
        "Be conversational and natural. Ask one question at a time."
    )


def get_worker_options() -> WorkerOptions:
    from app.config import settings

    return WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        num_idle_processes=2,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
        ws_url=settings.livekit_url,
    )


if __name__ == "__main__":
    cli.run_app(get_worker_options())
