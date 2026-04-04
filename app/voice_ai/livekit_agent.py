"""LiveKit Voice AI Agent — replaces the custom VoiceAISession.

Uses LiveKit's Agent + AgentSession with:
  - STT: Deepgram (streaming, via livekit-plugins-deepgram)
  - VAD: Silero (built-in, via livekit-plugins-silero)
  - LLM: SarvamLLM plugin (wraps existing Groq/Sarvam engine)
  - TTS: Deepgram Aura (fast, low-latency)

Barge-in: When the agent detects caller speech during TTS (via VAD),
it publishes a {"type": "barge_in"} data message so the Plivo bridge
can send clearAudio to stop queued audio on the caller's end.
"""

from __future__ import annotations

import asyncio
import json
import logging
import warnings

# Suppress pydantic "model_" namespace warnings from livekit-agents internals
warnings.filterwarnings("ignore", message=".*Field.*model_.*protected namespace.*")

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    TurnHandlingOptions,
    WorkerOptions,
    cli,
)
from livekit.plugins import deepgram, silero

from app.voice_ai.sarvam_llm_plugin import SarvamLLM

logger = logging.getLogger(__name__)


def prewarm(proc: JobProcess) -> None:
    """Pre-load the Silero VAD model tuned for telephony audio."""
    proc.userdata["vad"] = silero.VAD.load(
        min_speech_duration=0.05,     # 50ms — detect very short speech
        min_silence_duration=0.3,     # 300ms — faster end-of-speech for phone calls (default 550ms too slow)
        prefix_padding_duration=0.3,  # 300ms context before speech starts
        activation_threshold=0.45,    # slightly more sensitive for telephony noise
        sample_rate=8000,             # match Plivo telephony input (avoid unnecessary resample)
    )


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
    # Tenant's custom AI prompt (passed via room metadata from bridge)
    custom_system_prompt = metadata.get("ai_system_prompt")

    logger.info(
        "LiveKit agent joining room %s (tenant=%s, conv=%s, lang=%s, custom_prompt=%s)",
        ctx.room.name, tenant_id, conversation_id, language,
        "yes" if custom_system_prompt else "no",
    )

    from app.config import settings as _settings

    # VAD from prewarm or load fresh
    vad = ctx.proc.userdata.get("vad") or silero.VAD.load()

    # LLM plugin — pass tenant's custom prompt if available
    llm_plugin = SarvamLLM(
        language=language,
        company_name=company_name,
        system_prompt=custom_system_prompt,
    )

    # Deepgram Aura TTS — fast, low-latency, same API key as STT
    tts_plugin = deepgram.TTS(
        api_key=_settings.deepgram_api_key,
        model="aura-asteria-en",
    )

    # Deepgram nova-3 STT — tuned for telephony
    stt_plugin = deepgram.STT(
        api_key=_settings.deepgram_api_key,
        language=_deepgram_lang(language),
        model="nova-3",
        smart_format=True,
        endpointing_ms=300,
        no_delay=True,
        filler_words=False,
        punctuate=True,
        sample_rate=8000,
    )

    # Create agent — instructions are a fallback; the SarvamLLM plugin
    # uses its own system prompt (from tenant config or SYSTEM_PROMPTS).
    agent = Agent(
        instructions=custom_system_prompt or _get_instructions(language, company_name),
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
        vad=vad,
    )

    # Handle data messages from supervisor / backend (whisper / barge / handoff)
    @ctx.room.on("data_received")
    def _on_data(packet: rtc.DataPacket) -> None:
        try:
            msg = json.loads(packet.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return

        msg_type = msg.get("type")
        if msg_type == "whisper":
            llm_plugin.inject_system_hint(msg.get("message", ""))
            logger.info("Supervisor whisper received for room %s", ctx.room.name)
        elif msg_type in ("barge", "handoff"):
            logger.info("%s received for room %s — disconnecting agent", msg_type, ctx.room.name)
            asyncio.create_task(_graceful_disconnect(msg.get("reason", msg_type)))

    # Start the session — greeting is already played by the Plivo bridge
    # Turn handling tuned for telephony:
    #   - Adaptive interruption: ML model on LiveKit Cloud distinguishes true
    #     barge-in from backchannels ("uh-huh", "okay"). Faster than VAD-only
    #     in 64% of cases. Free on LiveKit Cloud.
    #   - Dynamic endpointing: adapts delay based on conversation pace.
    #   - Low min_duration for responsive interruption on phone calls.
    #   - Resume false interruptions so agent continues after "uh-huh".
    session = AgentSession(
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
        vad=vad,
        aec_warmup_duration=0.5,     # 500ms AEC warmup (telephony echo is predictable)
        turn_handling=TurnHandlingOptions(
            turn_detection="stt",
            endpointing={
                "mode": "dynamic",   # adapts delay to conversation pace
                "min_delay": 0.3,    # 300ms silence = end of turn (fast)
                "max_delay": 1.0,    # cap at 1s for longer pauses
            },
            interruption={
                "enabled": True,
                "mode": "adaptive",  # ML-based: filters backchannels, faster true barge-in
                "min_duration": 0.15, # 150ms speech to trigger analysis
                "min_words": 0,
                "resume_false_interruption": True,
                "false_interruption_timeout": 2.0,  # wait 2s before declaring false interruption
            },
        ),
    )

    await session.start(agent, room=ctx.room)
    logger.info("LiveKit agent started in room %s", ctx.room.name)

    # --- Barge-in + end-call/escalation detection ---
    @session.on("agent_state_changed")
    def _on_agent_state(event, **kwargs) -> None:
        if event.old_state == "speaking" and event.new_state == "listening":
            # Barge-in: tell bridge to clear Plivo audio
            logger.info("Agent interrupted (barge-in) in room %s", ctx.room.name)
            asyncio.create_task(_publish_barge_in())

            # After speaking, check if LLM flagged end-call or escalation
            if llm_plugin.should_end_call:
                logger.info("LLM flagged end-call — disconnecting (room=%s)", ctx.room.name)
                asyncio.create_task(_end_call())
            elif llm_plugin.should_escalate:
                logger.info("LLM flagged escalation — triggering handoff (room=%s)", ctx.room.name)
                asyncio.create_task(_trigger_escalation())

    @session.on("user_state_changed")
    def _on_user_state(event, **kwargs) -> None:
        if event.new_state == "speaking" and session.agent_state == "speaking":
            logger.info("User speaking during agent speech — sending early barge-in")
            asyncio.create_task(_publish_barge_in())

    async def _publish_barge_in() -> None:
        try:
            await ctx.room.local_participant.publish_data(
                json.dumps({"type": "barge_in"}).encode(),
                reliable=True,
                topic="bridge-control",
            )
        except Exception:
            logger.warning("Failed to publish barge_in signal", exc_info=True)

    async def _graceful_disconnect(reason: str) -> None:
        """Stop the AI pipeline and leave the room."""
        logger.info("Graceful disconnect: reason=%s, room=%s", reason, ctx.room.name)
        try:
            await session.aclose()
        except Exception:
            logger.warning("Error closing agent session", exc_info=True)
        try:
            await ctx.room.disconnect()
        except Exception:
            logger.warning("Error disconnecting from room", exc_info=True)

    async def _end_call() -> None:
        """End the call after the farewell TTS finishes playing.
        Wait briefly so the caller hears the goodbye, then trigger hangup."""
        await asyncio.sleep(2.0)  # let farewell audio play through
        if conversation_id:
            try:
                from app.db.engine import async_session_factory
                from app.core.handoff_engine import handoff_engine
                from app.core.state_machine import Trigger
                from uuid import UUID
                async with async_session_factory() as db:
                    for trigger in (Trigger.AI_RESOLVED, Trigger.DISPOSITION_SUBMITTED):
                        try:
                            await handoff_engine.process_trigger(
                                db=db,
                                conversation_id=UUID(conversation_id),
                                trigger=trigger,
                                metadata={"reason": "AI ended call", "disposition": "resolved"},
                            )
                        except Exception:
                            continue
                    await db.commit()
                logger.info("Call ended by AI for conv=%s", conversation_id)
            except Exception:
                logger.warning("Failed to end call via state machine", exc_info=True)
        await _graceful_disconnect("end_call")

    async def _trigger_escalation() -> None:
        """Trigger AI→Human escalation via the handoff engine."""
        if conversation_id:
            try:
                from app.db.engine import async_session_factory
                from app.core.handoff_engine import handoff_engine
                from app.core.state_machine import Trigger
                from uuid import UUID
                async with async_session_factory() as db:
                    await handoff_engine.process_trigger(
                        db=db,
                        conversation_id=UUID(conversation_id),
                        trigger=Trigger.AI_TRANSFER,
                        metadata={"reason": llm_plugin._escalation_reason or "AI escalation"},
                    )
                    await db.commit()
                logger.info("Escalation triggered for conv=%s", conversation_id)
            except Exception:
                logger.warning("Failed to trigger escalation", exc_info=True)
        # Don't disconnect — the handoff engine will send a "handoff" data message
        # which triggers _graceful_disconnect via the _on_data handler.


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
