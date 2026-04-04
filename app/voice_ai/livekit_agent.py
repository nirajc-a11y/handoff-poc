"""LiveKit Voice AI Agent — replaces the custom VoiceAISession.

Uses LiveKit's Agent + AgentSession with:
  - STT: Deepgram (streaming, via livekit-plugins-deepgram)
  - VAD: Silero (built-in, via livekit-plugins-silero)
  - LLM: Groq via openai.LLM (OpenAI-compatible endpoint)
  - TTS: Deepgram Aura (English) / Sarvam Bulbul v3 (Hindi/Marathi)

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
    EndpointingOptions,
    InterruptionOptions,
    JobContext,
    JobProcess,
    TurnHandlingOptions,
    WorkerOptions,
    cli,
)
from livekit.agents.voice.room_io import RoomOptions
from livekit.plugins import deepgram, openai, silero

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Escalation / end-call keyword detection
# ---------------------------------------------------------------------------
_ESCALATION_PHRASES = {
    "transfer you", "connect you with", "connect you to",
    "let me get a human", "speak to a human", "human agent",
    "transferring you", "connecting you",
}
_ESCALATION_PHRASES_MR = {
    "तुम्हाला जोडतो", "एजंटशी जोडतो", "माणसाशी बोलू",
}

_END_CALL_PHRASES = {
    "goodbye", "good bye", "have a great day", "have a nice day",
    "thank you for calling", "thanks for calling", "take care",
}
_END_CALL_PHRASES_MR = {
    "धन्यवाद", "बाय", "शुभ दिवस",
}

_USER_ESCALATION_KEYWORDS = {
    "agent", "human", "representative", "operator", "real person",
    "speak to someone", "help", "manager",
}
_USER_ESCALATION_KEYWORDS_MR = {
    "एजंट", "माणूस", "मदत", "कोणाशी बोलायचं", "तक्रार", "व्यवस्थापक",
}


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------
_SYSTEM_PROMPTS: dict[str, str] = {
    "en": (
        "You are Maya, a professional customer support agent for {company_name}. "
        "Be warm, natural, and brief.\n\n"
        "RULES:\n"
        "- Max 1 short sentence per turn. Then STOP and WAIT for the customer to respond.\n"
        "- Be conversational and natural, like a real person. Don't sound scripted.\n"
        "- Ask one question at a time. Don't overwhelm with multiple questions.\n"
        "- Use simple, clear language. Avoid jargon.\n"
        "- NEVER use bullet points, lists, markdown, or formatting — this is spoken audio.\n"
        "- If the customer seems frustrated, acknowledge their feelings first.\n"
        "- If you cannot resolve the issue within 3 exchanges, offer to connect them to a human agent.\n"
        "- Never make up information. If unsure, say you'll check and connect them to a specialist.\n"
        "- Never say \"I'm going to wait\" or narrate what you're doing. Just wait silently for their response.\n\n"
        "{company_name} offers: Cloud hosting plans (Basic $29/mo, Pro $79/mo, Enterprise $199/mo), "
        "24/7 technical support, domain registration, SSL certificates, and managed databases.\n\n"
        "Common issues: Password resets, billing disputes, plan upgrades/downgrades, "
        "service outages, DNS configuration, SSL renewal."
    ),
    "mr": (
        "तुम्ही {company_name} च्या व्यावसायिक ग्राहक सेवा एजंट आहात. तुमचे नाव माया आहे. "
        "तुम्ही उबदार, मैत्रीपूर्ण आणि व्यावसायिक स्वरात बोलता.\n\n"
        "नियम:\n"
        "- प्रत्येक वळणावर जास्तीत जास्त 1 लहान वाक्य. मग थांबा आणि ग्राहकाच्या उत्तराची वाट पहा.\n"
        "- एका वेळी एक प्रश्न विचारा.\n"
        "- सोपी, स्पष्ट भाषा वापरा.\n"
        "- जर ग्राहक निराश असेल तर प्रथम त्यांच्या भावना मान्य करा.\n"
        "- जर 3 देवाणघेवाणीत समस्या सोडवता आली नाही तर मानवी एजंटशी जोडण्याची ऑफर द्या.\n"
        "- माहिती बनवू नका. अनिश्चित असल्यास, तज्ञांशी जोडण्याची ऑफर द्या.\n\n"
        "पूर्णपणे मराठीत उत्तर द्या. इंग्रजी शब्द टाळा."
    ),
}


def _build_system_prompt(
    language: str,
    company_name: str,
    custom_prompt: str | None = None,
) -> str:
    """Build the full system prompt."""
    if custom_prompt:
        return custom_prompt
    template = _SYSTEM_PROMPTS.get(language, _SYSTEM_PROMPTS["en"])
    return template.format(company_name=company_name)


def prewarm(proc: JobProcess) -> None:
    """Pre-load the Silero VAD model tuned for telephony audio."""
    proc.userdata["vad"] = silero.VAD.load(
        min_speech_duration=0.05,     # 50ms — detect very short speech
        min_silence_duration=settings.vad_min_silence_duration,
        prefix_padding_duration=0.3,
        activation_threshold=settings.vad_activation_threshold,
        sample_rate=8000,
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
    custom_system_prompt = metadata.get("ai_system_prompt")

    logger.info(
        "LiveKit agent joining room %s (tenant=%s, conv=%s, lang=%s, custom_prompt=%s)",
        ctx.room.name, tenant_id, conversation_id, language,
        "yes" if custom_system_prompt else "no",
    )

    from app.config import settings as _settings

    # VAD from prewarm or load fresh
    vad = ctx.proc.userdata.get("vad") or silero.VAD.load()

    # LLM — Groq via OpenAI-compatible endpoint
    llm_plugin = openai.LLM(
        model=_settings.groq_model,
        base_url="https://api.groq.com/openai/v1",
        api_key=_settings.groq_api_key,
        temperature=0.7,
    )

    # TTS selection based on language
    if language in ("hi", "mr"):
        from app.voice_ai.sarvam_tts_plugin import SarvamTTS
        tts_plugin = SarvamTTS(
            language=language,
            speaker=_settings.sarvam_tts_speaker,
        )
        logger.info("Using Sarvam TTS for language=%s", language)
    else:
        tts_plugin = deepgram.TTS(
            api_key=_settings.deepgram_api_key,
            model=_settings.deepgram_tts_model,
        )
        logger.info("Using Deepgram Aura TTS for language=%s", language)

    # Deepgram nova-3 STT — tuned for telephony
    stt_plugin = deepgram.STT(
        api_key=_settings.deepgram_api_key,
        language=_deepgram_lang(language),
        model=_settings.deepgram_stt_model,
        smart_format=True,
        endpointing_ms=_settings.deepgram_endpointing_ms,
        no_delay=True,
        filler_words=False,
        punctuate=True,
        sample_rate=8000,
    )

    # Build system prompt
    base_prompt = _build_system_prompt(language, company_name, custom_system_prompt)
    supervisor_hints: list[str] = []

    # Create agent with turn handling on the Agent (like reference POC)
    agent = Agent(
        instructions=base_prompt,
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
        vad=vad,
        turn_handling=TurnHandlingOptions(
            turn_detection="vad",
            endpointing=EndpointingOptions(
                min_delay=0.3,
                max_delay=0.8,
            ),
            interruption=InterruptionOptions(
                enabled=True,
                mode="vad",
                min_duration=0.3,
                min_words=1,
                resume_false_interruption=True,
            ),
        ),
        allow_interruptions=True,
    )

    # Closure state for escalation detection
    escalation_reason: str | None = None

    # Handle data messages from supervisor / backend (whisper / barge / handoff)
    @ctx.room.on("data_received")
    def _on_data(packet: rtc.DataPacket) -> None:
        nonlocal supervisor_hints
        try:
            msg = json.loads(packet.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return

        msg_type = msg.get("type")
        if msg_type == "whisper":
            hint = msg.get("message", "")
            supervisor_hints.append(hint)
            hints_block = "\n".join(f"[Supervisor guidance]: {h}" for h in supervisor_hints)
            asyncio.create_task(
                agent.update_instructions(f"{base_prompt}\n\n{hints_block}")
            )
            logger.info("Supervisor whisper received for room %s", ctx.room.name)
        elif msg_type in ("barge", "handoff"):
            logger.info("%s received for room %s — disconnecting agent", msg_type, ctx.room.name)
            asyncio.create_task(_graceful_disconnect(msg.get("reason", msg_type)))

    # Start session — clean, no deprecated options
    session = AgentSession(
        aec_warmup_duration=0.5,
    )

    await session.start(
        agent,
        room=ctx.room,
        room_options=RoomOptions(
            participant_identity="plivo-bridge",
            close_on_disconnect=True,
        ),
    )
    logger.info("LiveKit agent started in room %s", ctx.room.name)

    # Wait for the plivo-bridge participant to connect, then generate greeting
    async def _greet():
        try:
            participant = await ctx.wait_for_participant(identity="plivo-bridge")
            logger.info("Plivo bridge connected: %s", participant.identity)
            # Let the LLM generate the greeting naturally
            session.generate_reply(
                instructions="The customer just connected to the call. Greet them warmly, introduce yourself, and ask how you can help today."
            )
        except RuntimeError:
            logger.warning("Session closed before greeting could be sent")

    asyncio.create_task(_greet())

    # --- Escalation / end-call detection via conversation events ---
    esc_phrases = _ESCALATION_PHRASES | (_ESCALATION_PHRASES_MR if language == "mr" else set())
    end_phrases = _END_CALL_PHRASES | (_END_CALL_PHRASES_MR if language == "mr" else set())

    @session.on("conversation_item_added")
    def _on_conversation_item(event) -> None:
        nonlocal escalation_reason
        item = event.item
        if not hasattr(item, "role") or item.role != "assistant":
            return
        text_lower = (getattr(item, "text_content", None) or "").lower()
        if not text_lower:
            return

        if any(p in text_lower for p in esc_phrases):
            escalation_reason = "AI offered transfer"
            logger.info("LLM flagged escalation in room %s", ctx.room.name)
            asyncio.create_task(_trigger_escalation())
        elif any(p in text_lower for p in end_phrases):
            logger.info("LLM flagged end-call in room %s", ctx.room.name)
            asyncio.create_task(_end_call())

    # --- Barge-in signaling ---
    @session.on("agent_state_changed")
    def _on_agent_state(event, **kwargs) -> None:
        if event.old_state == "speaking" and event.new_state == "listening":
            logger.info("Agent interrupted (barge-in) in room %s", ctx.room.name)
            asyncio.create_task(_publish_barge_in())

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
                        metadata={"reason": escalation_reason or "AI escalation"},
                    )
                    await db.commit()
                logger.info("Escalation triggered for conv=%s", conversation_id)
            except Exception:
                logger.warning("Failed to trigger escalation", exc_info=True)


def _deepgram_lang(language: str) -> str:
    return {"en": "en-US", "hi": "hi", "mr": "mr"}.get(language, "en-US")


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
