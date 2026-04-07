"""LiveKit Voice AI Agent — replaces the custom VoiceAISession.

Uses LiveKit's Agent + AgentSession with:
  - STT: Deepgram nova-3 (streaming, via livekit-plugins-deepgram)
  - VAD: Silero (built-in, via livekit-plugins-silero)
  - LLM: Groq via openai.LLM (llama-4-scout, fast tool calling)
  - TTS: Deepgram Aura (English) / Sarvam Bulbul v3 (Hindi/Marathi)

Barge-in: When the agent detects caller speech during TTS (via VAD),
it publishes a {"type": "barge_in"} data message so the Plivo bridge
can send clearAudio to stop queued audio on the caller's end.

End-call and escalation are handled via LLM function tools, not keyword matching.
"""

from __future__ import annotations

import asyncio
import json
import logging
import warnings

# Suppress pydantic "model_" namespace warnings from livekit-agents internals
warnings.filterwarnings("ignore", message=".*Field.*model_.*protected namespace.*")

from livekit import api, rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    EndpointingOptions,
    InterruptionOptions,
    JobContext,
    JobProcess,
    RunContext,
    TurnHandlingOptions,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.agents.voice.room_io import RoomOptions
from livekit.plugins import deepgram, openai, silero

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompts — natural, identity-aware, optimized for spoken audio
# ---------------------------------------------------------------------------
_SYSTEM_PROMPTS: dict[str, str] = {
    "en": (
        "You are Maya, a warm and helpful customer support agent at {company_name}. "
        "You're on a live phone call right now.\n\n"
        "How to speak:\n"
        "- One short sentence per turn, then stop and listen. Never monologue.\n"
        "- Sound human: use contractions, natural pacing, occasional 'Sure', 'Got it', 'Of course'.\n"
        "- No lists, no bullet points, no markdown — you're speaking, not writing.\n"
        "- Ask only one question at a time.\n\n"
        "What to do:\n"
        "- If the caller asks for a human or you can't help after 2 tries, call transfer_to_human.\n"
        "- If they say goodbye or want to hang up, call end_call.\n"
        "- Never make up facts. If unsure, say you'll connect them to someone who can help.\n"
        "- Never identify yourself as an AI."
    ),
    "mr": (
        "तुम्ही {company_name} मधील माया आहात, एक मदतनीस ग्राहक सेवा प्रतिनिधी. "
        "तुम्ही आत्ता लाइव्ह फोन कॉलवर आहात.\n\n"
        "बोलण्याची पद्धत:\n"
        "- प्रत्येक वेळी एक छोटे वाक्य बोला, मग थांबा आणि ऐका.\n"
        "- नैसर्गिकपणे बोला. यादी किंवा फॉरमॅटिंग वापरू नका.\n"
        "- एका वेळी एकच प्रश्न विचारा.\n\n"
        "काय करायचे:\n"
        "- 2 प्रयत्नांनंतर मदत न झाल्यास किंवा मानवी एजंट मागितल्यास transfer_to_human वापरा.\n"
        "- निरोप घेताना end_call वापरा.\n"
        "- खोटी माहिती देऊ नका. AI म्हणून स्वतःचा उल्लेख करू नका.\n"
        "- पूर्णपणे मराठीत उत्तर द्या."
    ),
}


_VOICE_CALL_RULES = (
    "\n\nRemember: live phone call. One short sentence, then wait. No lists or formatting ever."
)


def _build_system_prompt(
    language: str,
    company_name: str,
    custom_prompt: str | None = None,
) -> str:
    """Build the full system prompt.

    Custom prompts provide persona/knowledge (who you are, what you know).
    We always wrap them with voice call rules (how to behave on a phone call).
    This prevents the LLM from hallucinating greeting responses to non-greeting
    inputs when using a bare tenant-supplied prompt.
    """
    if custom_prompt:
        return custom_prompt + _VOICE_CALL_RULES
    template = _SYSTEM_PROMPTS.get(language, _SYSTEM_PROMPTS["en"])
    return template.format(company_name=company_name)


def prewarm(proc: JobProcess) -> None:
    """Pre-load the Silero VAD model tuned for telephony audio."""
    proc.userdata["vad"] = silero.VAD.load(
        min_speech_duration=0.05,     # 50ms — detect very short speech
        min_silence_duration=settings.vad_min_silence_duration,
        prefix_padding_duration=0.3,
        activation_threshold=settings.vad_activation_threshold,
    )


async def entrypoint(ctx: JobContext) -> None:
    """Main agent entrypoint — called once per LiveKit room."""
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Extract configuration from room metadata.
    # The agent may join before LiveKit syncs the metadata set at room creation
    # (race condition with pre-warmed rooms). Retry for up to 2s if empty.
    metadata = {}
    for _attempt in range(10):
        if ctx.room.metadata:
            try:
                metadata = json.loads(ctx.room.metadata)
                break  # parsed successfully
            except json.JSONDecodeError:
                logger.warning("Failed to parse room metadata: %s", ctx.room.metadata)
                break  # malformed — no point retrying
        await asyncio.sleep(0.2)
    else:
        logger.warning("Room metadata still empty after retries: %s", ctx.room.name)

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

    # LLM — Groq via OpenAI-compatible endpoint (llama-4-scout: fast + good tool calling)
    # groq_model can be overridden per-tenant via room metadata
    groq_model = metadata.get("groq_model") or _settings.groq_model
    llm_plugin = openai.LLM(
        model=groq_model,
        base_url="https://api.groq.com/openai/v1",
        api_key=_settings.groq_api_key,
        temperature=0.2,
        timeout=_settings.llm_timeout_seconds,
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
    )

    # Build system prompt
    base_prompt = _build_system_prompt(language, company_name, custom_system_prompt)
    supervisor_hints: list[str] = []

    # --- Function tools (replace keyword-based detection) ---
    room_name = ctx.room.name
    hangup_scheduled = False
    _disconnecting = False

    @function_tool(
        name="end_call",
        description="End the phone call. Use when the conversation is complete, the caller says goodbye or asks to hang up, or the call cannot proceed.",
    )
    async def tool_end_call(ctx: RunContext, reason: str = "") -> str:
        logger.info("TOOL end_call: reason=%s, room=%s", reason, room_name)
        asyncio.create_task(_end_call())
        return "Call ending. Say a brief goodbye."

    @function_tool(
        name="transfer_to_human",
        description="Transfer the caller to a human agent. Use when you cannot resolve the issue, the caller asks for a human, or the situation requires human judgment.",
    )
    async def tool_transfer_to_human(ctx: RunContext, reason: str = "") -> str:
        logger.info("TOOL transfer_to_human: reason=%s, room=%s", reason, room_name)
        asyncio.create_task(_trigger_escalation(reason or "Customer needs human assistance"))
        return "Transferring now. Let the caller know you're connecting them."

    # Create agent with tuned turn handling (aligned with sample reference)
    agent = Agent(
        instructions=base_prompt,
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
        vad=vad,
        tools=[tool_end_call, tool_transfer_to_human],
        turn_handling=TurnHandlingOptions(
            turn_detection="vad",
            endpointing=EndpointingOptions(
                min_delay=0.1,   # respond quickly after silence — 100ms is enough for telephony
                max_delay=0.6,   # don't wait a full second if VAD is uncertain
            ),
            interruption=InterruptionOptions(
                enabled=True,
                mode="vad",
                min_duration=0.15,  # allow short words like "wait", "stop", "no" to interrupt
                min_words=1,        # single-word interruptions must work
                resume_false_interruption=True,
            ),
        ),
        allow_interruptions=True,
    )

    # ---------------------------------------------------------------------------
    # Transcript publishing via Redis pub/sub
    # The main FastAPI process subscribes to "transcript.added" and persists
    # Message records to the DB, then publishes "conversation.message_added".
    # ---------------------------------------------------------------------------

    async def _publish_transcript(sender_type: str, content: str) -> None:
        if not conversation_id or not tenant_id or not content.strip():
            return
        try:
            import redis.asyncio as aioredis
            # Create a fresh connection per publish — the agent runs in a
            # subprocess with its own event loop, so the shared singleton pool
            # from the main process cannot be reused (different loop error).
            async with aioredis.from_url(
                _settings.redis_url,
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
            ) as r:
                await r.publish(
                    "transcript.added",
                    json.dumps({
                        "conversation_id": conversation_id,
                        "tenant_id": tenant_id,
                        "sender_type": sender_type,
                        "content": content.strip(),
                    }),
                )
        except Exception:
            logger.warning("Failed to publish transcript to Redis", exc_info=True)

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

    # Start session
    session = AgentSession(
        aec_warmup_duration=0.1,  # reduced from 0.3 — saves 200ms; telephony echo is handled at network level
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

    @session.on("user_input_transcribed")
    def _on_user_transcript(ev) -> None:
        if ev.is_final and ev.transcript.strip():
            asyncio.create_task(_publish_transcript("customer", ev.transcript))

    @session.on("conversation_item_added")
    def _on_conversation_item(ev) -> None:
        item = ev.item
        if getattr(item, "role", None) == "assistant":
            text = getattr(item, "text_content", None)
            # Skip interrupted items — text may be truncated mid-sentence
            if text and not getattr(item, "interrupted", False):
                asyncio.create_task(_publish_transcript("ai", text))

    @session.on("close")
    def _on_session_close(*_):
        logger.info("Session closed: room=%s", ctx.room.name)
        if not hangup_scheduled and not _disconnecting:
            logger.warning("Session closed without scheduled hangup — forcing disconnect")
            asyncio.create_task(_end_call())

    # Wait for the plivo-bridge participant to connect, then stay silent.
    # The bridge plays the cached TTS greeting directly to the caller via
    # stream_greeting() — no LLM round-trip needed. The agent's first response
    # will be to the caller's first utterance.
    async def _greet():
        try:
            participant = await ctx.wait_for_participant(identity="plivo-bridge")
            logger.info("Plivo bridge connected: %s", participant.identity)
            # Greeting handled by bridge.stream_greeting() — agent waits for caller.
        except RuntimeError:
            logger.warning("Session closed before bridge connected")

    asyncio.create_task(_greet())

    async def _graceful_disconnect(reason: str) -> None:
        nonlocal _disconnecting
        _disconnecting = True
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
        nonlocal hangup_scheduled
        if hangup_scheduled:
            return  # Prevent duplicate hangup tasks
        hangup_scheduled = True

        # Wait for all pending TTS speech to finish playing
        try:
            await session.drain()
            logger.info("Speech drained, proceeding with hangup")
        except Exception as e:
            logger.warning("Drain failed, falling back to delay: %s", e)
            await asyncio.sleep(3.0)

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

        # Remove plivo-bridge participant to force call hangup on the Plivo side
        try:
            lk_api = api.LiveKitAPI(
                _settings.livekit_url,
                _settings.livekit_api_key,
                _settings.livekit_api_secret,
            )
            await lk_api.room.remove_participant(
                api.RoomParticipantIdentity(
                    room=ctx.room.name,
                    identity="plivo-bridge",
                )
            )
            await lk_api.aclose()
            logger.info("Plivo bridge removed — call ended: room=%s", ctx.room.name)
        except Exception as e:
            logger.warning("Failed to remove plivo-bridge participant: %s", e)

        await _graceful_disconnect("end_call")

    async def _trigger_escalation(reason: str = "") -> None:
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
                        metadata={"reason": reason or "AI escalation"},
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
