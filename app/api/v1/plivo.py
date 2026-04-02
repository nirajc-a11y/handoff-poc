"""Plivo-specific webhook endpoints that return Plivo XML to control call flow.

Plivo uses XML responses (similar to Twilio's TwiML) with elements like
``<Speak>``, ``<GetDigits>``, ``<Conference>``, ``<Wait>``, ``<Play>``, and
``<Redirect>`` to drive call behaviour.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.handoff_engine import handoff_engine
from app.core.ivr_engine import IVRAction, ivr_engine
from app.core.state_machine import ConversationState, StateMachineError, Trigger
from app.db.models.channel_session import ChannelSession
from app.db.models.conversation import Conversation
from app.db.models.ivr_menu import IVRMenu
from app.dependencies import get_db
from app.config import settings
from app.providers.base import CallState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plivo", tags=["plivo"])

# Base URL for absolute webhook URLs (Plivo requires absolute URLs)
_BASE = settings.base_webhook_url.rstrip("/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _abs(path: str) -> str:
    """Make a path absolute using the configured webhook base URL."""
    return f"{_BASE}{path}"


# Plivo language codes for <Speak> — improves pronunciation for Indian languages.
# Uses built-in WOMAN voice (always available, no Polly addon needed).
_PLIVO_LANG = {"en": "en-IN", "hi": "hi-IN", "mr": "hi-IN"}


def _speak(text: str, language: str = "en") -> str:
    """Generate a <Speak> tag with Indian English voice."""
    lang_code = _PLIVO_LANG.get(language, "en-IN")
    escaped = _escape_xml(text)
    return f'<Speak voice="WOMAN" language="{lang_code}">{escaped}</Speak>'


def xml_response(xml: str) -> Response:
    """Return a Plivo XML response with text/xml content type (required by Plivo)."""
    return Response(content=xml.strip(), media_type="text/xml")


def _escape_xml(text: str) -> str:
    """Escape special XML characters in user-provided text."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


async def _start_call_recording(tenant_id: str, call_uuid: str, conv_id: str):
    """Start full-call recording via Plivo REST API (fire-and-forget)."""
    import asyncio
    try:
        import plivo as _plivo
        client = _plivo.RestClient(settings.plivo_auth_id, settings.plivo_auth_token)
        recording_cb = _abs(
            f"/api/v1/plivo/recording-status?tenant_id={tenant_id}&conv_id={conv_id}"
        )
        await asyncio.to_thread(
            lambda: client.calls.record(
                call_uuid,
                time_limit=3600,
                file_format="mp3",
                callback_url=recording_cb,
                callback_method="POST",
            )
        )
        logger.info("Started call recording for %s (conv=%s)", call_uuid, conv_id)
    except Exception:
        logger.exception("Failed to start recording for call %s", call_uuid)


async def _find_or_create_conversation(
    db: AsyncSession,
    tenant_id: str,
    call_uuid: str,
    from_number: str,
    to_number: str,
    direction: str,
) -> Conversation:
    """Find an existing conversation for this call or create a new one."""
    tenant_uuid = uuid.UUID(tenant_id)

    # 1. Try to find by provider_session_id (exact match on CallUUID)
    stmt = (
        select(ChannelSession)
        .where(
            ChannelSession.provider == "plivo",
            ChannelSession.provider_session_id == call_uuid,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is not None:
        conv_stmt = select(Conversation).where(Conversation.id == session.conversation_id)
        conv_result = await db.execute(conv_stmt)
        conversation = conv_result.scalar_one_or_none()
        if conversation is not None:
            return conversation

    # 2. For outbound calls, find the most recent active conversation to this number
    #    (Plivo request_uuid and CallUUID may differ)
    customer_number = to_number if direction == "outbound" else from_number
    active_stmt = (
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_uuid,
            Conversation.channel == "voice",
            Conversation.customer_identifier == customer_number,
            Conversation.state.notin_(["ended", "failed"]),
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    active_result = await db.execute(active_stmt)
    existing_conv = active_result.scalar_one_or_none()

    if existing_conv is not None:
        # Update the channel session with the real CallUUID
        update_stmt = (
            select(ChannelSession)
            .where(ChannelSession.conversation_id == existing_conv.id)
            .order_by(ChannelSession.created_at.desc())
            .limit(1)
        )
        update_result = await db.execute(update_stmt)
        existing_session = update_result.scalar_one_or_none()
        if existing_session is not None:
            existing_session.provider_session_id = call_uuid
            await db.flush()
        return existing_conv

    # 3. Create a new conversation (for truly new inbound calls)
    conversation = Conversation(
        tenant_id=tenant_uuid,
        channel="voice",
        direction=direction,
        customer_identifier=customer_number,
        state=ConversationState.INITIATED.value,
        current_handler_type="system",
        started_at=datetime.now(timezone.utc),
        context={},
    )
    db.add(conversation)
    await db.flush()

    channel_session = ChannelSession(
        tenant_id=tenant_uuid,
        conversation_id=conversation.id,
        channel="voice",
        provider="plivo",
        provider_session_id=call_uuid,
        status="initiated",
        direction=direction,
        from_address=from_number,
        to_address=to_number,
        started_at=datetime.now(timezone.utc),
    )
    db.add(channel_session)
    await db.flush()

    return conversation


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/answer")
async def plivo_answer(request: Request, db: AsyncSession = Depends(get_db)):
    """Called when an inbound call is answered or an outbound call connects.

    Returns IVR XML: speak a welcome message and gather DTMF digits for menu
    navigation.
    """
    form = await request.form()
    tenant_id = request.query_params.get("tenant_id", "")
    call_uuid = form.get("CallUUID", "")
    from_number = form.get("From", "")
    to_number = form.get("To", "")
    direction = form.get("Direction", "inbound")

    # Normalise direction
    direction = "inbound" if "inbound" in str(direction).lower() else "outbound"

    if not tenant_id:
        logger.warning("Plivo /answer called without tenant_id")
        return xml_response(
            f"<Response>{_speak('System error. Please try again later.')}</Response>"
        )

    try:
        # Find or create the conversation
        conversation = await _find_or_create_conversation(
            db,
            tenant_id=tenant_id,
            call_uuid=str(call_uuid),
            from_number=str(from_number),
            to_number=str(to_number),
            direction=direction,
        )

        # Transition to IVR — try the appropriate trigger based on current state
        current_state = conversation.state
        try:
            if current_state == ConversationState.INITIATED.value:
                # Need RING then ANSWER
                conversation = await handoff_engine.process_trigger(
                    db=db, conversation_id=conversation.id, trigger=Trigger.RING,
                )
                conversation = await handoff_engine.process_trigger(
                    db=db, conversation_id=conversation.id, trigger=Trigger.ANSWER,
                )
            elif current_state == ConversationState.RINGING.value:
                # Just need ANSWER
                conversation = await handoff_engine.process_trigger(
                    db=db, conversation_id=conversation.id, trigger=Trigger.ANSWER,
                    metadata={"provider": "plivo", "provider_session_id": str(call_uuid)},
                )
            elif current_state in (ConversationState.IVR.value, ConversationState.AI_HANDLING.value,
                                    ConversationState.HUMAN_HANDLING.value):
                # Already past IVR — that's fine, just serve the IVR XML anyway
                pass
            else:
                logger.warning("Plivo /answer: unexpected state %s for conv %s", current_state, conversation.id)
        except StateMachineError as sme:
            logger.warning("Plivo /answer state transition failed: %s (continuing with IVR XML)", sme)
            await db.rollback()
            stmt = select(Conversation).where(Conversation.id == conversation.id)
            result = await db.execute(stmt)
            conversation = result.scalar_one()

        # Load the IVR menu for this tenant
        tenant_uuid = uuid.UUID(tenant_id)
        try:
            prompt, menu_id = await ivr_engine.get_menu_prompt(
                db, tenant_id=tenant_uuid
            )
        except ValueError:
            prompt = "Welcome. Please hold while we connect you to an agent."
            menu_id = None

        # Build the action URL for DTMF callback (must be absolute for Plivo)
        conv_id = str(conversation.id)
        menu_param = f"&amp;menu_id={menu_id}" if menu_id else ""
        action_url = _abs(
            f"/api/v1/plivo/dtmf?tenant_id={tenant_id}"
            f"&amp;conv_id={conv_id}{menu_param}"
        )

        speak_prompt = _speak(prompt)
        speak_goodbye = _speak("We did not receive any input. Goodbye.")
        xml = f"""<Response>
    <GetDigits action="{action_url}" method="POST" timeout="10" numDigits="1" retries="2">
        {speak_prompt}
    </GetDigits>
    {speak_goodbye}
</Response>"""

        await db.commit()

        # Start call-level recording for inbound calls
        if call_uuid and settings.plivo_auth_id:
            import asyncio as _aio
            _aio.create_task(_start_call_recording(tenant_id, str(call_uuid), conv_id))

        return xml_response(xml)

    except Exception:
        logger.exception("Error in plivo_answer")
        await db.rollback()
        return xml_response(
            f"<Response>{_speak('Sorry, we are experiencing technical difficulties. Please try again later.')}</Response>"
        )


@router.post("/dtmf")
async def plivo_dtmf(request: Request, db: AsyncSession = Depends(get_db)):
    """Called when a customer enters DTMF digits during the IVR menu.

    Routes based on the digit pressed and the action type configured for
    that IVR menu option.
    """
    form = await request.form()
    digits = str(form.get("Digits", ""))
    tenant_id = request.query_params.get("tenant_id", "")
    conv_id = request.query_params.get("conv_id", "")
    menu_id_str = request.query_params.get("menu_id", "")

    if not tenant_id or not conv_id:
        return xml_response(
            f"<Response>{_speak('System error. Goodbye.')}</Response>"
        )

    try:
        tenant_uuid = uuid.UUID(tenant_id)
        conversation_id = uuid.UUID(conv_id)

        # Process the DTMF digit through the IVR engine
        if menu_id_str:
            menu_uuid = uuid.UUID(menu_id_str)
            action = await ivr_engine.process_dtmf(
                db,
                tenant_id=tenant_uuid,
                menu_id=menu_uuid,
                digit=digits,
            )
        else:
            action = IVRAction(
                action_type="play_message",
                message="No menu configured. Please try again later.",
            )

        # Route based on action type
        if action.action_type == "ai_handoff":
            return await _handle_ai_handoff(
                db, conversation_id, tenant_id, conv_id, action
            )

        elif action.action_type == "human_queue":
            return await _handle_human_queue(
                db, conversation_id, tenant_id, conv_id, action
            )

        elif action.action_type == "submenu":
            return await _handle_submenu(
                db, tenant_uuid, tenant_id, conv_id, action
            )

        elif action.action_type == "play_message":
            message = _escape_xml(action.message or "Invalid option.")
            # Replay the current menu after the message
            menu_param = f"&amp;menu_id={menu_id_str}" if menu_id_str else ""
            action_url = _abs(
                f"/api/v1/plivo/dtmf?tenant_id={tenant_id}"
                f"&amp;conv_id={conv_id}{menu_param}"
            )
            s_msg = _speak(action.message or "Invalid option.")
            s_sel = _speak("Please make a selection.")
            s_bye = _speak("We did not receive any input. Goodbye.")
            xml = f"""<Response>
    {s_msg}
    <GetDigits action="{action_url}" method="POST" timeout="10" numDigits="1" retries="1">
        {s_sel}
    </GetDigits>
    {s_bye}
</Response>"""
            return xml_response(xml)

        elif action.action_type == "hangup":
            s = _speak(action.message or "Thank you for calling. Goodbye.")
            return xml_response(f"<Response>{s}</Response>")

        else:
            logger.warning("Unknown IVR action type: %s", action.action_type)
            s = _speak("Invalid option. Please try again later. Goodbye.")
            return xml_response(f"<Response>{s}</Response>"
            )

    except Exception:
        logger.exception("Error in plivo_dtmf")
        await db.rollback()
        return xml_response(
            f"<Response>{_speak('Sorry, an error occurred. Please try again later.')}</Response>"
        )


async def _handle_ai_handoff(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    tenant_id: str,
    conv_id: str,
    action: IVRAction,
) -> Response:
    """Transition to AI handling and return XML that greets the customer."""
    try:
        await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=Trigger.DTMF_AI,
            metadata={
                "provider": "plivo",
                "action_config": action.target_config,
            },
        )
        await db.commit()
    except StateMachineError as exc:
        logger.warning("AI handoff state transition failed: %s", exc)

    lang = (action.target_config or {}).get("language", "en")

    # Check voice AI mode from tenant config
    from app.db.models.tenant import Tenant
    tenant_result = await db.execute(
        select(Tenant.config).where(Tenant.id == uuid.UUID(tenant_id))
    )
    tenant_config = tenant_result.scalar_one_or_none() or {}
    voice_mode = tenant_config.get("voice_ai_mode", "plivo")
    sarvam_speaker = tenant_config.get("sarvam_speaker", "ritu")
    logger.info("AI handoff: voice_mode=%s, lang=%s, speaker=%s", voice_mode, lang, sarvam_speaker)

    if voice_mode == "livekit" and not settings.sarvam_api_key:
        logger.error(
            "LiveKit/Sarvam mode selected for tenant %s but SARVAM_API_KEY is empty — falling back to Plivo mode",
            tenant_id,
        )
        voice_mode = "plivo"

    if voice_mode == "livekit":
        # Mode B: Real-time AI via Plivo <Stream> + Sarvam
        # Sarvam generates the greeting via TTS over the WebSocket for consistent voice.
        stream_ws_url = _BASE.replace("https://", "wss://").replace("http://", "ws://")
        stream_url = (
            f"{stream_ws_url}/api/v1/plivo/audio-stream"
            f"?tenant_id={tenant_id}&conv_id={conv_id}&language={lang}&speaker={sarvam_speaker}"
        )
        escaped_url = _escape_xml(stream_url)
        xml = f"""<Response>
    <Stream bidirectional="true" contentType="audio/x-mulaw;rate=8000" keepCallAlive="true" streamTimeout="1800">{escaped_url}</Stream>
</Response>"""
        return xml_response(xml)

    # Mode A (default): Record + transcribe + LLM + Plivo TTS
    greeting_text = (
        action.target_config.get("greeting", "")
        if action.target_config
        else ""
    ) or "You are now connected to our AI assistant. How can I help you today?"

    s_greet = _speak(greeting_text, language=lang)

    # After greeting, record customer speech using Plivo <Record>
    # When recording finishes, Plivo POSTs the recording URL to /ai-turn
    ai_turn_url = _abs(
        f"/api/v1/plivo/ai-turn?tenant_id={tenant_id}"
        f"&amp;conv_id={conv_id}&amp;language={lang}&amp;turn=0"
    )
    escalate_url = _abs(
        f"/api/v1/plivo/escalate-to-human?tenant_id={tenant_id}&amp;conv_id={conv_id}"
    )

    xml = f"""<Response>
    {s_greet}
    <Record action="{ai_turn_url}" method="POST" maxLength="15" timeout="2" finishOnKey="#" redirect="true" />
    {_speak("I didn't hear anything. Let me connect you to an agent.", language=lang)}
    <Redirect method="POST">{escalate_url}</Redirect>
</Response>"""
    return xml_response(xml)


async def _handle_human_queue(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    tenant_id: str,
    conv_id: str,
    action: IVRAction,
) -> Response:
    """Transition to human queue and return hold-music XML."""
    try:
        await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=Trigger.DTMF_HUMAN,
            metadata={
                "provider": "plivo",
                "action_config": action.target_config,
                "required_skills": (action.target_config or {}).get("required_skills"),
            },
        )
        await db.commit()
    except StateMachineError as exc:
        logger.warning("Human queue state transition failed: %s", exc)

    # Put the customer into a conference room so an agent can join later
    cb_url = _abs(f"/api/v1/plivo/conference-events?tenant_id={tenant_id}&amp;conv_id={conv_id}")
    wait_url = _abs("/api/v1/plivo/hold-music")
    s = _speak("Please hold while we connect you to an agent.")
    xml = f"""<Response>
    {s}
    <Conference callbackUrl="{cb_url}" waitSound="{wait_url}" enterSound="" startConferenceOnEnter="false" endConferenceOnExit="false" stayAlone="true" maxMembers="10">room-{conv_id}</Conference>
</Response>"""
    return xml_response(xml)


async def _handle_submenu(
    db: AsyncSession,
    tenant_uuid: uuid.UUID,
    tenant_id: str,
    conv_id: str,
    action: IVRAction,
) -> Response:
    """Navigate to a sub-menu and return its prompt XML."""
    lang = (action.target_config or {}).get("language", "en")
    if action.target_id is None:
        s = _speak("Menu not configured. Goodbye.", language=lang)
        return xml_response(f"<Response>{s}</Response>")

    try:
        prompt, menu_id = await ivr_engine.get_menu_prompt(
            db, tenant_id=tenant_uuid, menu_id=action.target_id
        )
    except ValueError:
        s = _speak("Menu not found. Goodbye.", language=lang)
        return xml_response(f"<Response>{s}</Response>")

    action_url = _abs(
        f"/api/v1/plivo/dtmf?tenant_id={tenant_id}"
        f"&amp;conv_id={conv_id}&amp;menu_id={menu_id}"
    )

    s_prompt = _speak(prompt, language=lang)
    s_bye = _speak("We did not receive any input. Goodbye.", language=lang)
    xml = f"""<Response>
    <GetDigits action="{action_url}" method="POST" timeout="10" numDigits="1" retries="2">
        {s_prompt}
    </GetDigits>
    {s_bye}
</Response>"""
    return xml_response(xml)


@router.post("/connect-agent")
async def plivo_connect_agent(request: Request):
    """Return XML that places the call into a conference room.

    The ``conf_name`` query parameter specifies the room.  An agent joining
    the same room creates a live bridge between customer and agent.
    """
    form = await request.form()
    conf_name = request.query_params.get("conf_name", "")
    target = request.query_params.get("target", "")

    if target:
        # Cold transfer: dial the target number directly
        xml = f"""<Response>
    <Dial>
        <Number>{_escape_xml(target)}</Number>
    </Dial>
</Response>"""
        return xml_response(xml)

    if not conf_name:
        call_uuid = form.get("CallUUID", "unknown")
        conf_name = f"room-{call_uuid}"

    cb_url = _abs("/api/v1/plivo/conference-events")
    xml = f"""<Response>
    <Conference callbackUrl="{cb_url}" enterSound="beep:1" startConferenceOnEnter="true" endConferenceOnExit="false" stayAlone="true" maxMembers="10">{_escape_xml(conf_name)}</Conference>
</Response>"""
    return xml_response(xml)


@router.post("/hold-music")
async def plivo_hold_music(request: Request):
    """Return XML that plays hold music / comfort messages in a loop.

    Plivo does not support ``<Play loop="0">`` with ``<Wait>`` in the same
    ``<Response>``, so we use ``<Speak>`` and ``<Wait>`` to simulate a hold
    experience, with a ``<Redirect>`` to loop back.
    """
    redirect_url = _abs("/api/v1/plivo/hold-music")
    s1 = _speak("Please hold while we connect you to an agent.")
    s2 = _speak("Thank you for your patience. An agent will be with you shortly.")
    return xml_response(f"""<Response>
    {s1}
    <Wait length="30" />
    {s2}
    <Wait length="30" />
    <Redirect method="POST">{redirect_url}</Redirect>
</Response>""")


@router.post("/ai-turn")
async def plivo_ai_turn(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle one turn of AI conversation using Plivo Record + Groq Whisper + LLM.

    Flow: Plivo records customer speech → POSTs RecordUrl here →
    we download audio → Groq Whisper transcribes → Groq LLM responds →
    return <Speak> response + <Record> for next turn.
    """
    from app.core.ai_engine import ai_engine
    from app.db.models.message import Message
    import os

    form = await request.form()
    tenant_id = request.query_params.get("tenant_id", "")
    conv_id = request.query_params.get("conv_id", "")
    language = request.query_params.get("language", "en")
    turn = int(request.query_params.get("turn", "0"))

    # Plivo Record callback sends RecordUrl with the audio
    record_url = str(form.get("RecordUrl", "")).strip()
    record_duration = str(form.get("RecordingDuration", "0")).strip()

    escalate_url = _abs(
        f"/api/v1/plivo/escalate-to-human?tenant_id={tenant_id}&amp;conv_id={conv_id}"
    )

    conv_uuid = uuid.UUID(conv_id) if conv_id else None
    tenant_uuid = uuid.UUID(tenant_id) if tenant_id else None

    # If no recording or too short, retry or escalate
    if not record_url or float(record_duration or 0) < 0.5:
        if turn >= 2:
            return xml_response(f"""<Response>
    {_speak("I could not hear you. Let me connect you to a human agent.", language=language)}
    <Redirect method="POST">{escalate_url}</Redirect>
</Response>""")

        next_url = _abs(
            f"/api/v1/plivo/ai-turn?tenant_id={tenant_id}"
            f"&amp;conv_id={conv_id}&amp;language={language}&amp;turn={turn + 1}"
        )
        return xml_response(f"""<Response>
    {_speak("I am listening. Please go ahead and speak after the beep.", language=language)}
    <Record action="{next_url}" method="POST" maxLength="15" timeout="2" finishOnKey="#" redirect="true" />
    {_speak("I didn't hear anything. Let me connect you to an agent.", language=language)}
    <Redirect method="POST">{escalate_url}</Redirect>
</Response>""")

    logger.info("AI turn %d: recording received (%ss) from %s", turn, record_duration, record_url)

    # Step 1: Save recording to local file
    recording_filename = None
    try:
        import httpx as httpx_client
        async with httpx_client.AsyncClient(timeout=15.0) as http:
            audio_resp = await http.get(record_url)
            audio_resp.raise_for_status()
            audio_data = audio_resp.content

        recordings_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "recordings")
        os.makedirs(recordings_dir, exist_ok=True)
        recording_filename = f"{conv_id}_{turn}_{int(datetime.now(timezone.utc).timestamp())}.mp3"
        recording_path = os.path.join(recordings_dir, recording_filename)
        with open(recording_path, "wb") as f:
            f.write(audio_data)
        logger.info("Saved recording: %s (%d bytes)", recording_filename, len(audio_data))

        # Save recording as audio message
        if conv_uuid and tenant_uuid:
            audio_msg = Message(
                tenant_id=tenant_uuid,
                conversation_id=conv_uuid,
                sender_type="customer",
                content_type="audio",
                content=f"/recordings/{recording_filename}",
                metadata_={"recording_url": record_url, "duration": record_duration, "turn": turn},
            )
            db.add(audio_msg)
            await db.flush()
    except Exception:
        logger.exception("Failed to save recording")

    # Step 2: Transcribe with Groq Whisper (pass pre-downloaded audio to avoid second download)
    speech_text = ""
    try:
        speech_text = await ai_engine.transcribe_audio(record_url, audio_data=audio_data)
    except Exception:
        logger.exception("Transcription failed")

    if not speech_text:
        # Whisper returned empty — retry or escalate
        if turn >= 2:
            return xml_response(f"""<Response>
    {_speak("I could not understand. Let me connect you to a human agent.", language=language)}
    <Redirect method="POST">{escalate_url}</Redirect>
</Response>""")

        next_url = _abs(
            f"/api/v1/plivo/ai-turn?tenant_id={tenant_id}"
            f"&amp;conv_id={conv_id}&amp;language={language}&amp;turn={turn + 1}"
        )
        return xml_response(f"""<Response>
    {_speak("I could not understand that. Could you please repeat?", language=language)}
    <Record action="{next_url}" method="POST" maxLength="15" timeout="2" finishOnKey="#" redirect="true" />
</Response>""")

    logger.info("AI turn %d: customer said: %s", turn, speech_text)

    # Step 3: Save customer text message + transcript
    if conv_uuid and tenant_uuid:
        try:
            text_msg = Message(
                tenant_id=tenant_uuid,
                conversation_id=conv_uuid,
                sender_type="customer",
                content_type="text",
                content=speech_text,
                metadata_={"source": "whisper_transcription", "turn": turn},
            )
            db.add(text_msg)
            await db.flush()
        except Exception:
            logger.exception("Failed to save customer text message")

    # Step 4: Build conversation history
    history = []
    if conv_uuid:
        try:
            msg_stmt = (
                select(Message)
                .where(
                    Message.conversation_id == conv_uuid,
                    Message.content_type == "text",
                )
                .order_by(Message.created_at.asc())
            )
            msg_result = await db.execute(msg_stmt)
            for m in msg_result.scalars():
                if m.sender_type == "customer":
                    history.append({"role": "user", "content": m.content or ""})
                elif m.sender_type in ("ai", "agent"):
                    history.append({"role": "assistant", "content": m.content or ""})
        except Exception:
            pass

    # Step 5: Call LLM
    try:
        ai_response = await ai_engine.process_message(
            customer_message=speech_text,
            conversation_history=history,
            language=language,
        )

        # Save AI response
        if conv_uuid and tenant_uuid:
            ai_msg = Message(
                tenant_id=tenant_uuid,
                conversation_id=conv_uuid,
                sender_type="ai",
                content_type="text",
                content=ai_response.text,
                metadata_={"confidence": ai_response.confidence, "should_escalate": ai_response.should_escalate, "turn": turn},
            )
            db.add(ai_msg)

            conv_stmt = select(Conversation).where(Conversation.id == conv_uuid)
            conv_result = await db.execute(conv_stmt)
            conv = conv_result.scalar_one_or_none()
            if conv:
                conv.ai_confidence_score = ai_response.confidence
                if ai_response.escalation_reason:
                    conv.ai_escalation_reason = ai_response.escalation_reason

        await db.commit()
        logger.info("AI response (confidence=%.2f, escalate=%s): %s",
                     ai_response.confidence, ai_response.should_escalate, ai_response.text[:100])

    except Exception:
        logger.exception("AI engine failed")
        ai_response = type("R", (), {
            "text": "I'm having trouble right now. Let me connect you to an agent.",
            "should_escalate": True, "confidence": 0.0, "escalation_reason": "ai_error",
        })()

    # Step 6: Respond
    if ai_response.should_escalate:
        s = _speak(ai_response.text + " Let me connect you to a human agent.", language=language)
        return xml_response(f"""<Response>
    {s}
    <Redirect method="POST">{escalate_url}</Redirect>
</Response>""")

    # Speak AI response + record next turn
    next_url = _abs(
        f"/api/v1/plivo/ai-turn?tenant_id={tenant_id}"
        f"&amp;conv_id={conv_id}&amp;language={language}&amp;turn={turn + 1}"
    )
    s_response = _speak(ai_response.text, language=language)
    return xml_response(f"""<Response>
    {s_response}
    <Record action="{next_url}" method="POST" maxLength="15" timeout="2" finishOnKey="#" redirect="true" />
    {_speak("I didn't hear a response. Let me connect you to an agent.", language=language)}
    <Redirect method="POST">{escalate_url}</Redirect>
</Response>""")


@router.post("/escalate-to-human")
async def plivo_escalate_to_human(request: Request, db: AsyncSession = Depends(get_db)):
    """Escalate from AI to human agent — transition state and return hold music."""
    from app.db.models.message import Message

    tenant_id = request.query_params.get("tenant_id", "")
    conv_id = request.query_params.get("conv_id", "")

    if conv_id:
        try:
            conv_uuid = uuid.UUID(conv_id)
            await handoff_engine.process_trigger(
                db=db,
                conversation_id=conv_uuid,
                trigger=Trigger.AI_TRANSFER,
                metadata={"reason": "AI escalation via voice call", "provider": "plivo"},
            )
            await db.commit()
        except (StateMachineError, Exception) as exc:
            logger.warning("Escalation state transition failed: %s", exc)

    # Return hold music while waiting for human agent
    cb_url = _abs(f"/api/v1/plivo/conference-events?tenant_id={tenant_id}&amp;conv_id={conv_id}")
    wait_url = _abs("/api/v1/plivo/hold-music")
    s = _speak("Please hold while we connect you to an agent.")
    return xml_response(f"""<Response>
    {s}
    <Conference callbackUrl="{cb_url}" waitSound="{wait_url}" enterSound="" startConferenceOnEnter="false" endConferenceOnExit="false" stayAlone="true" maxMembers="10">room-{conv_id}</Conference>
</Response>""")


@router.post("/conference-events")
async def plivo_conference_events(
    request: Request, db: AsyncSession = Depends(get_db)
):
    """Handle Plivo conference callbacks (member joined, member left, etc.).

    This can be used to detect when an agent joins or leaves the conference
    and trigger the appropriate state transitions.
    """
    form = await request.form()
    conference_name = str(form.get("ConferenceName", ""))
    event = str(form.get("ConferenceAction", ""))
    member_id = str(form.get("ConferenceMemberID", ""))
    call_uuid = str(form.get("CallUUID", ""))
    tenant_id = request.query_params.get("tenant_id", "")
    conv_id = request.query_params.get("conv_id", "")

    logger.info(
        "Plivo conference event: conf=%s action=%s member=%s call=%s",
        conference_name,
        event,
        member_id,
        call_uuid,
    )

    # Publish events for downstream handling
    if event == "enter" and conv_id:
        # An agent has joined the conference -- this could trigger AGENT_ASSIGNED
        logger.info(
            "Conference member joined: conf=%s, conv_id=%s, call=%s",
            conference_name,
            conv_id,
            call_uuid,
        )

    elif event == "exit" and conv_id:
        logger.info(
            "Conference member left: conf=%s, conv_id=%s, call=%s",
            conference_name,
            conv_id,
            call_uuid,
        )

    return xml_response("<Response></Response>")


@router.post("/call-status")
async def plivo_call_status(
    request: Request, db: AsyncSession = Depends(get_db)
):
    """Handle Plivo call status change callbacks.

    Plivo sends these when a call transitions between states (ringing,
    in-progress, completed, busy, failed, no-answer, canceled).
    """
    form = await request.form()
    call_uuid = str(form.get("CallUUID", ""))
    status = str(form.get("CallStatus", "")).lower()
    direction = str(form.get("Direction", ""))
    from_number = str(form.get("From", ""))
    to_number = str(form.get("To", ""))
    tenant_id = request.query_params.get("tenant_id", "")

    logger.info(
        "Plivo call status: uuid=%s status=%s direction=%s from=%s to=%s",
        call_uuid,
        status,
        direction,
        from_number,
        to_number,
    )

    if not call_uuid:
        return {"status": "ignored", "reason": "missing_call_uuid"}

    # Map Plivo status to our CallState
    status_map: dict[str, CallState] = {
        "ringing": CallState.RINGING,
        "answered": CallState.ANSWERED,
        "in-progress": CallState.ANSWERED,
        "completed": CallState.ENDED,
        "busy": CallState.BUSY,
        "no-answer": CallState.NO_ANSWER,
        "failed": CallState.FAILED,
        "canceled": CallState.FAILED,
    }

    call_state = status_map.get(status)
    if call_state is None:
        logger.warning("Unknown Plivo call status: %s", status)
        return {"status": "ignored", "reason": f"unknown_status_{status}"}

    # Find the channel session for this call (try by UUID first, then by phone number)
    stmt = (
        select(ChannelSession)
        .where(
            ChannelSession.provider == "plivo",
            ChannelSession.provider_session_id == call_uuid,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    # Fallback: find by phone number if UUID doesn't match (request_uuid != CallUUID)
    if session is None and (from_number or to_number):
        customer_number = to_number if "outbound" in direction.lower() else from_number
        fallback_stmt = (
            select(ChannelSession)
            .join(Conversation, Conversation.id == ChannelSession.conversation_id)
            .where(
                ChannelSession.provider == "plivo",
                Conversation.customer_identifier == customer_number,
                Conversation.state.notin_(["ended", "failed"]),
            )
            .order_by(ChannelSession.created_at.desc())
            .limit(1)
        )
        fb_result = await db.execute(fallback_stmt)
        session = fb_result.scalar_one_or_none()
        if session is not None:
            # Update the session with the real CallUUID
            session.provider_session_id = call_uuid
            await db.flush()
            logger.info("Found Plivo session by phone number fallback: %s", customer_number)

    if session is None:
        logger.info(
            "No ChannelSession for Plivo call %s -- ignoring status %s",
            call_uuid,
            status,
        )
        return {"status": "ignored", "reason": "session_not_found"}

    # Update session status
    session.status = call_state.value
    session.provider_metadata = {
        **(session.provider_metadata or {}),
        "last_status": status,
        "last_status_payload": dict(form),
    }

    if call_state == CallState.ENDED:
        session.ended_at = datetime.now(timezone.utc)

    await db.flush()

    # Map call state to a trigger for the handoff engine
    trigger_map: dict[CallState, Trigger] = {
        CallState.RINGING: Trigger.RING,
        CallState.ANSWERED: Trigger.ANSWER,
        CallState.ENDED: Trigger.CUSTOMER_DISCONNECT,
        CallState.FAILED: Trigger.ERROR,
        CallState.BUSY: Trigger.BUSY,
        CallState.NO_ANSWER: Trigger.NO_ANSWER,
    }

    trigger = trigger_map.get(call_state)
    if trigger is None:
        await db.commit()
        return {"status": "ok", "call_state": call_state.value, "trigger": None}

    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=session.conversation_id,
            trigger=trigger,
            metadata={
                "provider": "plivo",
                "provider_session_id": call_uuid,
                "call_state": call_state.value,
                "raw_status": status,
            },
        )

        # Auto-end: if call ended (hangup) and state is now wrap_up,
        # automatically submit disposition to move to "ended"
        if call_state == CallState.ENDED and conversation.state == "wrap_up":
            try:
                conversation = await handoff_engine.process_trigger(
                    db=db,
                    conversation_id=session.conversation_id,
                    trigger=Trigger.DISPOSITION_SUBMITTED,
                    metadata={
                        "disposition": "call_completed",
                        "notes": "Auto-ended on hangup",
                        "auto_disposition": True,
                    },
                )
                logger.info("Auto-ended conversation %s on hangup", session.conversation_id)
            except StateMachineError:
                pass  # Already ended or in unexpected state — fine

        return {
            "status": "processed",
            "conversation_id": str(session.conversation_id),
            "call_state": call_state.value,
            "trigger": trigger.value,
            "new_state": conversation.state,
        }
    except StateMachineError as exc:
        # If CUSTOMER_DISCONNECT fails (e.g. conversation in ai_handling),
        # try to force-end it
        if call_state == CallState.ENDED:
            try:
                # Try multiple triggers that might work
                for t in [Trigger.AI_RESOLVED, Trigger.AGENT_END, Trigger.DISPOSITION_SUBMITTED]:
                    try:
                        conversation = await handoff_engine.process_trigger(
                            db=db,
                            conversation_id=session.conversation_id,
                            trigger=t,
                            metadata={"disposition": "call_completed", "auto_disposition": True},
                        )
                        if conversation.state in ("wrap_up", "ended"):
                            break
                    except StateMachineError:
                        continue

                # If now in wrap_up, auto-end
                if hasattr(conversation, "state") and conversation.state == "wrap_up":
                    try:
                        conversation = await handoff_engine.process_trigger(
                            db=db,
                            conversation_id=session.conversation_id,
                            trigger=Trigger.DISPOSITION_SUBMITTED,
                            metadata={"disposition": "call_completed", "auto_disposition": True},
                        )
                    except StateMachineError:
                        pass

                logger.info("Force-ended conversation %s on hangup", session.conversation_id)
                await db.commit()
                return {"status": "force_ended", "conversation_id": str(session.conversation_id)}
            except Exception:
                pass

        logger.warning(
            "Invalid state transition for conversation %s: %s",
            session.conversation_id,
            exc,
        )
        await db.commit()
        return {"status": "ignored", "reason": str(exc)}


@router.post("/recording-status")
async def plivo_recording_status(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Plivo recording callback — download and store full-call recording.

    Plivo POSTs here when a call-level recording is ready.  We download the
    MP3, save it locally, store the path on the conversation, and publish a
    WebSocket event so the frontend can show the player.
    """
    import os
    import httpx as httpx_client
    from app.core.events import Event, event_bus
    from app.db.models.message import Message

    form = await request.form()
    tenant_id = request.query_params.get("tenant_id", "")
    conv_id = request.query_params.get("conv_id", "")

    # Plivo calls.record() sends recording data as a JSON string in a `response` field
    import json as _json
    response_str = str(form.get("response", ""))
    if response_str:
        try:
            data = _json.loads(response_str)
        except (ValueError, TypeError):
            data = {}
    else:
        data = dict(form)

    record_url = str(data.get("record_url", "") or data.get("RecordUrl", "")).strip()
    recording_id = str(data.get("recording_id", "") or data.get("RecordingID", ""))
    record_duration = str(data.get("recording_duration", "0") or data.get("RecordingDuration", "0"))
    call_uuid = str(data.get("call_uuid", "") or data.get("CallUUID", ""))

    logger.info(
        "Recording status: id=%s url=%s duration=%s call=%s conv=%s",
        recording_id, record_url, record_duration, call_uuid, conv_id,
    )

    if not record_url:
        return {"status": "ignored", "reason": "no_record_url"}

    # Resolve conversation
    conversation_id = None
    tenant_uuid = None

    if conv_id and tenant_id:
        try:
            conversation_id = uuid.UUID(conv_id)
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            pass

    if conversation_id is None and call_uuid:
        stmt = (
            select(ChannelSession)
            .where(ChannelSession.provider == "plivo", ChannelSession.provider_session_id == call_uuid)
            .limit(1)
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if session:
            conversation_id = session.conversation_id
            tenant_uuid = session.tenant_id

    if conversation_id is None or tenant_uuid is None:
        logger.warning("Could not resolve conversation for recording %s (call %s)", recording_id, call_uuid)
        return {"status": "ignored", "reason": "conversation_not_found"}

    # Download the recording MP3 from Plivo
    recordings_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "recordings")
    os.makedirs(recordings_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"{conversation_id}_full_{timestamp}.mp3"
    filepath = os.path.join(recordings_dir, filename)

    try:
        async with httpx_client.AsyncClient(timeout=60.0) as http:
            resp = await http.get(record_url, follow_redirects=True)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)
        logger.info("Saved full-call recording: %s (%d bytes)", filename, len(resp.content))
    except Exception:
        logger.exception("Failed to download recording %s", recording_id)
        return {"status": "error", "reason": "download_failed"}

    # Update conversation with recording URL
    recording_path = f"/recordings/{filename}"
    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_result = await db.execute(conv_stmt)
    conv = conv_result.scalar_one_or_none()
    if conv:
        conv.recording_url = recording_path

    # Create a Message record
    message = Message(
        tenant_id=tenant_uuid,
        conversation_id=conversation_id,
        sender_type="system",
        content_type="audio",
        content=recording_path,
        metadata_={
            "type": "full_call_recording",
            "recording_id": recording_id,
            "recording_duration": record_duration,
            "recording_url": record_url,
            "call_uuid": call_uuid,
        },
    )
    db.add(message)
    await db.commit()

    # Publish WebSocket event
    await event_bus.publish(Event(
        topic="conversation.recording_ready",
        tenant_id=tenant_uuid,
        payload={"conversation_id": str(conversation_id), "recording_url": recording_path},
    ))

    return {"status": "ok", "conversation_id": str(conversation_id), "recording_url": recording_path}


@router.post("/fallback")
async def plivo_fallback(request: Request):
    """Fallback URL -- Plivo calls this if the answer_url fails."""
    return xml_response(
        f"<Response>{_speak('Sorry, we are experiencing technical difficulties. Please try again later.')}</Response>"
    )
