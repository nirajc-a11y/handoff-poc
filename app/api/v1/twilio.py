"""Twilio-specific webhook endpoints that return TwiML to control call flow.

Twilio uses TwiML (XML) responses with elements like ``<Say>``, ``<Gather>``,
``<Dial>``, ``<Conference>``, ``<Play>``, ``<Pause>``, and ``<Redirect>`` to
drive call behaviour.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.events import Event, event_bus
from app.core.handoff_engine import handoff_engine
from app.core.ivr_engine import IVRAction, ivr_engine
from app.core.state_machine import ConversationState, StateMachineError, Trigger
from app.db.models.channel_session import ChannelSession
from app.db.models.conversation import Conversation
from app.db.models.message import Message
from app.dependencies import get_db
from app.providers.base import CallState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/twilio", tags=["twilio"])

RECORDINGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "recordings",
)
os.makedirs(RECORDINGS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def twiml_response(twiml: str) -> Response:
    """Return a TwiML response with the correct content type."""
    return Response(content=twiml.strip(), media_type="application/xml")


def _escape_xml(text: str) -> str:
    """Escape special XML characters in user-provided text."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _say_tag(text: str, language: str = "en") -> str:
    """Return a ``<Say>`` TwiML element with the correct language attribute."""
    lang_code = "mr-IN" if language == "mr" else "en-US"
    return f'<Say language="{lang_code}">{_escape_xml(text)}</Say>'


def _lang_param(language: str) -> str:
    """Return the ``&amp;language=...`` query param fragment when non-default."""
    if language and language != "en":
        return f"&amp;language={_escape_xml(language)}"
    return ""


async def _find_or_create_conversation(
    db: AsyncSession,
    tenant_id: str,
    call_sid: str,
    from_number: str,
    to_number: str,
    direction: str,
) -> Conversation:
    """Find an existing conversation for this call or create a new one."""
    # Check if a channel session already exists for this call
    stmt = (
        select(ChannelSession)
        .where(
            ChannelSession.provider == "twilio",
            ChannelSession.provider_session_id == call_sid,
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

    # Create a new conversation
    tenant_uuid = uuid.UUID(tenant_id)
    conversation = Conversation(
        tenant_id=tenant_uuid,
        channel="voice",
        direction=direction,
        customer_identifier=from_number if direction == "inbound" else to_number,
        state=ConversationState.INITIATED.value,
        current_handler_type="system",
        started_at=datetime.now(timezone.utc),
        context={},
    )
    db.add(conversation)
    await db.flush()

    # Create the channel session
    channel_session = ChannelSession(
        tenant_id=tenant_uuid,
        conversation_id=conversation.id,
        channel="voice",
        provider="twilio",
        provider_session_id=call_sid,
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
async def twilio_answer(request: Request, db: AsyncSession = Depends(get_db)):
    """Called when an inbound call is answered or an outbound call connects.

    Returns TwiML with an IVR menu: speak a welcome message and gather DTMF
    digits for menu navigation.  Accepts an optional ``language`` query param
    (``en`` or ``mr``) that is propagated to all subsequent TwiML URLs.
    """
    form = await request.form()
    tenant_id = request.query_params.get("tenant_id", "")
    language = request.query_params.get("language", "en")
    call_sid = str(form.get("CallSid", ""))
    from_number = str(form.get("From", ""))
    to_number = str(form.get("To", ""))
    direction = str(form.get("Direction", "inbound"))

    # Normalise direction
    direction = "inbound" if "inbound" in direction.lower() else "outbound"

    if not tenant_id:
        logger.warning("Twilio /answer called without tenant_id")
        return twiml_response(
            f"<Response>{_say_tag('System error. Please try again later.', language)}</Response>"
        )

    try:
        # Find or create the conversation
        conversation = await _find_or_create_conversation(
            db,
            tenant_id=tenant_id,
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
            direction=direction,
        )

        # Store language in conversation context
        ctx = conversation.context or {}
        ctx["language"] = language
        conversation.context = ctx

        # Transition: INITIATED -> RINGING -> IVR
        try:
            conversation = await handoff_engine.process_trigger(
                db=db,
                conversation_id=conversation.id,
                trigger=Trigger.ANSWER,
                metadata={
                    "provider": "twilio",
                    "provider_session_id": call_sid,
                    "call_state": "answered",
                },
            )
        except StateMachineError:
            # The conversation might already be in IVR state (e.g. from a
            # status callback that arrived first).  That is acceptable.
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

        # Build the action URL for DTMF callback
        conv_id = str(conversation.id)
        menu_param = f"&amp;menu_id={menu_id}" if menu_id else ""
        lang = _lang_param(language)
        action_url = (
            f"/api/v1/twilio/dtmf?tenant_id={tenant_id}"
            f"&amp;conv_id={conv_id}{menu_param}{lang}"
        )

        say_prompt = _say_tag(prompt, language)
        no_input_msg = (
            "आम्हाला कोणताही इनपुट मिळाला नाही. गुडबाय."
            if language == "mr"
            else "We did not receive any input. Goodbye."
        )
        twiml = f"""<Response>
    <Gather action="{action_url}" method="POST" numDigits="1" timeout="10">
        {say_prompt}
    </Gather>
    {_say_tag(no_input_msg, language)}
</Response>"""

        await db.commit()
        return twiml_response(twiml)

    except Exception:
        logger.exception("Error in twilio_answer")
        await db.rollback()
        err_msg = (
            "क्षमस्व, तांत्रिक अडचण आली आहे. कृपया नंतर पुन्हा प्रयत्न करा."
            if language == "mr"
            else "Sorry, we are experiencing technical difficulties. Please try again later."
        )
        return twiml_response(
            f"<Response>{_say_tag(err_msg, language)}</Response>"
        )


@router.post("/dtmf")
async def twilio_dtmf(request: Request, db: AsyncSession = Depends(get_db)):
    """Called when a customer enters DTMF digits during the IVR menu.

    Routes based on the digit pressed and the action type configured for
    that IVR menu option.  The ``language`` query param is propagated.
    """
    form = await request.form()
    digits = str(form.get("Digits", ""))
    tenant_id = request.query_params.get("tenant_id", "")
    conv_id = request.query_params.get("conv_id", "")
    menu_id_str = request.query_params.get("menu_id", "")
    language = request.query_params.get("language", "en")

    if not tenant_id or not conv_id:
        return twiml_response(
            f"<Response>{_say_tag('System error. Goodbye.', language)}</Response>"
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

        # Check for language override in target_config
        if action.target_config and "language" in action.target_config:
            language = action.target_config["language"]

        # Route based on action type
        if action.action_type == "ai_handoff":
            return await _handle_ai_handoff(
                db, conversation_id, tenant_id, conv_id, action, language
            )

        elif action.action_type == "human_queue":
            return await _handle_human_queue(
                db, conversation_id, tenant_id, conv_id, action, language
            )

        elif action.action_type == "submenu":
            return await _handle_submenu(
                db, tenant_uuid, tenant_id, conv_id, action, language
            )

        elif action.action_type == "play_message":
            message = action.message or "Invalid option."
            # Replay the current menu after the message
            menu_param = f"&amp;menu_id={menu_id_str}" if menu_id_str else ""
            lang = _lang_param(language)
            action_url = (
                f"/api/v1/twilio/dtmf?tenant_id={tenant_id}"
                f"&amp;conv_id={conv_id}{menu_param}{lang}"
            )
            selection_msg = (
                "कृपया निवड करा."
                if language == "mr"
                else "Please make a selection."
            )
            no_input_msg = (
                "आम्हाला कोणताही इनपुट मिळाला नाही. गुडबाय."
                if language == "mr"
                else "We did not receive any input. Goodbye."
            )
            twiml = f"""<Response>
    {_say_tag(message, language)}
    <Gather action="{action_url}" method="POST" numDigits="1" timeout="10">
        {_say_tag(selection_msg, language)}
    </Gather>
    {_say_tag(no_input_msg, language)}
</Response>"""
            return twiml_response(twiml)

        elif action.action_type == "hangup":
            message = action.message or (
                "कॉल केल्याबद्दल धन्यवाद. गुडबाय."
                if language == "mr"
                else "Thank you for calling. Goodbye."
            )
            return twiml_response(f"<Response>{_say_tag(message, language)}</Response>")

        else:
            logger.warning("Unknown IVR action type: %s", action.action_type)
            err = (
                "अवैध पर्याय. कृपया नंतर पुन्हा प्रयत्न करा. गुडबाय."
                if language == "mr"
                else "Invalid option. Please try again later. Goodbye."
            )
            return twiml_response(
                f"<Response>{_say_tag(err, language)}</Response>"
            )

    except Exception:
        logger.exception("Error in twilio_dtmf")
        await db.rollback()
        err_msg = (
            "क्षमस्व, एक त्रुटी आली. कृपया नंतर पुन्हा प्रयत्न करा."
            if language == "mr"
            else "Sorry, an error occurred. Please try again later."
        )
        return twiml_response(
            f"<Response>{_say_tag(err_msg, language)}</Response>"
        )


async def _handle_ai_handoff(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    tenant_id: str,
    conv_id: str,
    action: IVRAction,
    language: str = "en",
) -> Response:
    """Transition to AI handling and return TwiML that greets the customer."""
    try:
        await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=Trigger.DTMF_AI,
            metadata={
                "provider": "twilio",
                "action_config": action.target_config,
            },
        )
        await db.commit()
    except StateMachineError as exc:
        logger.warning("AI handoff state transition failed: %s", exc)

    greeting = (
        action.target_config.get("greeting", "")
        if action.target_config
        else ""
    ) or (
        "तुम्ही आमच्या AI सहाय्यकाशी जोडले गेला आहात. मी तुम्हाला आज कशी मदत करू शकतो?"
        if language == "mr"
        else "You are now connected to our AI assistant. How can I help you today?"
    )

    goodbye_msg = (
        "आमच्या AI सहाय्यक वापरल्याबद्दल धन्यवाद. गुडबाय."
        if language == "mr"
        else "Thank you for using our AI assistant. Goodbye."
    )

    # In a full implementation this would stream to an AI speech engine.
    # For the POC we speak the greeting and then hold the line.
    twiml = f"""<Response>
    {_say_tag(greeting, language)}
    <Pause length="60" />
    {_say_tag(goodbye_msg, language)}
</Response>"""
    return twiml_response(twiml)


async def _handle_human_queue(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    tenant_id: str,
    conv_id: str,
    action: IVRAction,
    language: str = "en",
) -> Response:
    """Transition to human queue and return hold-music TwiML."""
    try:
        await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=Trigger.DTMF_HUMAN,
            metadata={
                "provider": "twilio",
                "action_config": action.target_config,
                "required_skills": (action.target_config or {}).get("required_skills"),
            },
        )
        await db.commit()
    except StateMachineError as exc:
        logger.warning("Human queue state transition failed: %s", exc)

    hold_msg = (
        "कृपया थांबा, आम्ही तुम्हाला एजंटशी जोडत आहोत."
        if language == "mr"
        else "Please hold while we connect you to an agent."
    )
    lang = _lang_param(language)

    recording_cb = f"/api/v1/twilio/recording-status?tenant_id={_escape_xml(tenant_id)}&amp;conv_id={_escape_xml(conv_id)}{lang}"
    conf_cb = f"/api/v1/twilio/conference-events?tenant_id={_escape_xml(tenant_id)}&amp;conv_id={_escape_xml(conv_id)}{lang}"
    hold_url = f"/api/v1/twilio/hold-music?language={_escape_xml(language)}"

    # Put the customer into a conference room so an agent can join later
    twiml = f"""<Response>
    {_say_tag(hold_msg, language)}
    <Dial>
        <Conference record="record-from-answer-dual" recordingStatusCallback="{recording_cb}" recordingStatusCallbackMethod="POST" statusCallback="{conf_cb}" statusCallbackEvent="join leave" startConferenceOnEnter="false" endConferenceOnExit="false" waitUrl="{hold_url}" waitMethod="POST">room-{_escape_xml(conv_id)}</Conference>
    </Dial>
</Response>"""
    return twiml_response(twiml)


async def _handle_submenu(
    db: AsyncSession,
    tenant_uuid: uuid.UUID,
    tenant_id: str,
    conv_id: str,
    action: IVRAction,
    language: str = "en",
) -> Response:
    """Navigate to a sub-menu and return its prompt TwiML."""
    if action.target_id is None:
        msg = (
            "मेनू कॉन्फिगर केलेला नाही. गुडबाय."
            if language == "mr"
            else "Menu not configured. Goodbye."
        )
        return twiml_response(
            f"<Response>{_say_tag(msg, language)}</Response>"
        )

    try:
        prompt, menu_id = await ivr_engine.get_menu_prompt(
            db, tenant_id=tenant_uuid, menu_id=action.target_id
        )
    except ValueError:
        msg = (
            "मेनू सापडला नाही. गुडबाय."
            if language == "mr"
            else "Menu not found. Goodbye."
        )
        return twiml_response(
            f"<Response>{_say_tag(msg, language)}</Response>"
        )

    lang = _lang_param(language)
    action_url = (
        f"/api/v1/twilio/dtmf?tenant_id={tenant_id}"
        f"&amp;conv_id={conv_id}&amp;menu_id={menu_id}{lang}"
    )

    no_input_msg = (
        "आम्हाला कोणताही इनपुट मिळाला नाही. गुडबाय."
        if language == "mr"
        else "We did not receive any input. Goodbye."
    )
    twiml = f"""<Response>
    <Gather action="{action_url}" method="POST" numDigits="1" timeout="10">
        {_say_tag(prompt, language)}
    </Gather>
    {_say_tag(no_input_msg, language)}
</Response>"""
    return twiml_response(twiml)


@router.post("/connect-agent")
async def twilio_connect_agent(request: Request):
    """Return TwiML that places the call into a conference room.

    The ``conf_name`` query parameter specifies the room.  An agent joining
    the same room creates a live bridge between customer and agent.
    """
    form = await request.form()
    conf_name = request.query_params.get("conf_name", "")
    target = request.query_params.get("target", "")
    tenant_id = request.query_params.get("tenant_id", "")
    conv_id = request.query_params.get("conv_id", "")

    if target:
        # Cold transfer: dial the target number directly
        twiml = f"""<Response>
    <Dial>{_escape_xml(target)}</Dial>
</Response>"""
        return twiml_response(twiml)

    if not conf_name:
        call_sid = str(form.get("CallSid", "unknown"))
        conf_name = f"room-{call_sid}"

    recording_cb = ""
    if tenant_id and conv_id:
        recording_cb = f' recordingStatusCallback="/api/v1/twilio/recording-status?tenant_id={_escape_xml(tenant_id)}&amp;conv_id={_escape_xml(conv_id)}" recordingStatusCallbackMethod="POST"'

    twiml = f"""<Response>
    <Dial>
        <Conference record="record-from-answer-dual"{recording_cb} beep="true" startConferenceOnEnter="true" endConferenceOnExit="false">{_escape_xml(conf_name)}</Conference>
    </Dial>
</Response>"""
    return twiml_response(twiml)


@router.post("/hold-music")
async def twilio_hold_music(request: Request):
    """Return TwiML that plays hold music / comfort messages in a loop.

    Uses ``<Say>`` and ``<Pause>`` with a ``<Redirect>`` to simulate a
    looping hold experience.
    """
    language = request.query_params.get("language", "en")

    hold_msg = (
        "कृपया थांबा, आम्ही तुम्हाला एजंटशी जोडत आहोत."
        if language == "mr"
        else "Please hold while we connect you to an agent."
    )
    patience_msg = (
        "तुमच्या संयमाबद्दल धन्यवाद. एक एजंट लवकरच तुम्हाला भेटेल."
        if language == "mr"
        else "Thank you for your patience. An agent will be with you shortly."
    )

    lang = _lang_param(language)
    redirect_url = f"/api/v1/twilio/hold-music?language={_escape_xml(language)}"

    return twiml_response(f"""<Response>
    {_say_tag(hold_msg, language)}
    <Pause length="30" />
    {_say_tag(patience_msg, language)}
    <Pause length="30" />
    <Redirect method="POST">{redirect_url}</Redirect>
</Response>""")


@router.post("/conference-events")
async def twilio_conference_events(
    request: Request, db: AsyncSession = Depends(get_db)
):
    """Handle Twilio conference status callbacks (participant joined/left, etc.).

    This can be used to detect when an agent joins or leaves the conference
    and trigger the appropriate state transitions.
    """
    form = await request.form()
    conference_sid = str(form.get("ConferenceSid", ""))
    friendly_name = str(form.get("FriendlyName", ""))
    status_event = str(form.get("StatusCallbackEvent", ""))
    call_sid = str(form.get("CallSid", ""))
    tenant_id = request.query_params.get("tenant_id", "")
    conv_id = request.query_params.get("conv_id", "")

    logger.info(
        "Twilio conference event: conf=%s name=%s event=%s call=%s",
        conference_sid,
        friendly_name,
        status_event,
        call_sid,
    )

    # Publish events for downstream handling
    if status_event == "participant-join" and conv_id:
        logger.info(
            "Conference participant joined: conf=%s, conv_id=%s, call=%s",
            friendly_name,
            conv_id,
            call_sid,
        )

    elif status_event == "participant-leave" and conv_id:
        logger.info(
            "Conference participant left: conf=%s, conv_id=%s, call=%s",
            friendly_name,
            conv_id,
            call_sid,
        )

    return twiml_response("<Response></Response>")


@router.post("/call-status")
async def twilio_call_status(
    request: Request, db: AsyncSession = Depends(get_db)
):
    """Handle Twilio call status change callbacks.

    Twilio sends these when a call transitions between states (initiated,
    ringing, in-progress, completed, busy, no-answer, failed, canceled).
    """
    form = await request.form()
    call_sid = str(form.get("CallSid", ""))
    status = str(form.get("CallStatus", "")).lower()
    direction = str(form.get("Direction", ""))
    from_number = str(form.get("From", ""))
    to_number = str(form.get("To", ""))
    tenant_id = request.query_params.get("tenant_id", "")

    logger.info(
        "Twilio call status: sid=%s status=%s direction=%s from=%s to=%s",
        call_sid,
        status,
        direction,
        from_number,
        to_number,
    )

    if not call_sid:
        return {"status": "ignored", "reason": "missing_call_sid"}

    # Map Twilio status to our CallState
    status_map: dict[str, CallState] = {
        "initiated": CallState.INITIATED,
        "ringing": CallState.RINGING,
        "in-progress": CallState.ANSWERED,
        "completed": CallState.ENDED,
        "busy": CallState.BUSY,
        "no-answer": CallState.NO_ANSWER,
        "failed": CallState.FAILED,
        "canceled": CallState.FAILED,
    }

    call_state = status_map.get(status)
    if call_state is None:
        logger.warning("Unknown Twilio call status: %s", status)
        return {"status": "ignored", "reason": f"unknown_status_{status}"}

    # Find the channel session for this call
    stmt = (
        select(ChannelSession)
        .where(
            ChannelSession.provider == "twilio",
            ChannelSession.provider_session_id == call_sid,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        logger.info(
            "No ChannelSession for Twilio call %s -- ignoring status %s",
            call_sid,
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
                "provider": "twilio",
                "provider_session_id": call_sid,
                "call_state": call_state.value,
                "raw_status": status,
            },
        )
        return {
            "status": "processed",
            "conversation_id": str(session.conversation_id),
            "call_state": call_state.value,
            "trigger": trigger.value,
            "new_state": conversation.state,
        }
    except StateMachineError as exc:
        logger.warning(
            "Invalid state transition for conversation %s: %s",
            session.conversation_id,
            exc,
        )
        await db.commit()
        return {"status": "ignored", "reason": str(exc)}


@router.post("/recording-status")
async def twilio_recording_status(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Twilio recording status callbacks.

    Downloads the completed recording from Twilio, saves it locally, creates
    a ``Message`` record with ``content_type='audio'``, and publishes a
    WebSocket event.
    """
    form = await request.form()
    recording_url = str(form.get("RecordingUrl", ""))
    recording_sid = str(form.get("RecordingSid", ""))
    recording_duration = str(form.get("RecordingDuration", "0"))
    call_sid = str(form.get("CallSid", ""))
    tenant_id = request.query_params.get("tenant_id", "")
    conv_id = request.query_params.get("conv_id", "")

    logger.info(
        "Recording status: sid=%s url=%s duration=%s call=%s",
        recording_sid,
        recording_url,
        recording_duration,
        call_sid,
    )

    if not recording_url:
        return {"status": "ignored", "reason": "no_recording_url"}

    # Resolve conversation -- prefer query param, fall back to ChannelSession lookup
    conversation_id: uuid.UUID | None = None
    tenant_uuid: uuid.UUID | None = None

    if conv_id and tenant_id:
        try:
            conversation_id = uuid.UUID(conv_id)
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            pass

    if conversation_id is None and call_sid:
        stmt = (
            select(ChannelSession)
            .where(
                ChannelSession.provider == "twilio",
                ChannelSession.provider_session_id == call_sid,
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if session is not None:
            conversation_id = session.conversation_id
            tenant_uuid = session.tenant_id

    if conversation_id is None or tenant_uuid is None:
        logger.warning(
            "Could not resolve conversation for recording %s (call %s)",
            recording_sid,
            call_sid,
        )
        return {"status": "ignored", "reason": "conversation_not_found"}

    # Download the recording WAV from Twilio (requires Basic auth)
    wav_url = f"{recording_url}.wav"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"{conversation_id}_{timestamp}.wav"
    filepath = os.path.join(RECORDINGS_DIR, filename)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                wav_url,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                follow_redirects=True,
                timeout=60.0,
            )
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)
        logger.info("Saved recording to %s (%d bytes)", filepath, len(resp.content))
    except Exception:
        logger.exception("Failed to download recording %s", recording_sid)
        return {"status": "error", "reason": "download_failed"}

    # Create a Message record
    message = Message(
        tenant_id=tenant_uuid,
        conversation_id=conversation_id,
        sender_type="system",
        content_type="audio",
        content=f"/recordings/{filename}",
        metadata_={
            "type": "recording",
            "recording_sid": recording_sid,
            "recording_duration": recording_duration,
            "recording_url": recording_url,
            "call_sid": call_sid,
        },
    )
    db.add(message)
    await db.commit()

    # Publish WebSocket event
    await event_bus.publish(
        Event(
            topic="conversation.recording",
            tenant_id=tenant_uuid,
            payload={
                "conversation_id": str(conversation_id),
                "message_id": str(message.id),
                "recording_path": f"/recordings/{filename}",
                "recording_sid": recording_sid,
                "duration": recording_duration,
            },
        )
    )

    return {"status": "ok", "message_id": str(message.id), "path": f"/recordings/{filename}"}


@router.post("/transcription")
async def twilio_transcription(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Twilio transcription callbacks.

    Creates a ``Message`` record with the transcription text and publishes a
    WebSocket event.
    """
    form = await request.form()
    transcription_text = str(form.get("TranscriptionText", ""))
    transcription_sid = str(form.get("TranscriptionSid", ""))
    call_sid = str(form.get("CallSid", ""))
    tenant_id = request.query_params.get("tenant_id", "")
    conv_id = request.query_params.get("conv_id", "")

    logger.info(
        "Transcription received: sid=%s call=%s text_length=%d",
        transcription_sid,
        call_sid,
        len(transcription_text),
    )

    if not transcription_text:
        return {"status": "ignored", "reason": "empty_transcription"}

    # Resolve conversation
    conversation_id: uuid.UUID | None = None
    tenant_uuid: uuid.UUID | None = None

    if conv_id and tenant_id:
        try:
            conversation_id = uuid.UUID(conv_id)
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            pass

    if conversation_id is None and call_sid:
        stmt = (
            select(ChannelSession)
            .where(
                ChannelSession.provider == "twilio",
                ChannelSession.provider_session_id == call_sid,
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if session is not None:
            conversation_id = session.conversation_id
            tenant_uuid = session.tenant_id

    if conversation_id is None or tenant_uuid is None:
        logger.warning(
            "Could not resolve conversation for transcription (call %s)",
            call_sid,
        )
        return {"status": "ignored", "reason": "conversation_not_found"}

    # Create a Message record
    message = Message(
        tenant_id=tenant_uuid,
        conversation_id=conversation_id,
        sender_type="system",
        content_type="text",
        content=transcription_text,
        metadata_={
            "type": "transcription",
            "transcription_sid": transcription_sid,
            "call_sid": call_sid,
        },
    )
    db.add(message)
    await db.commit()

    # Publish WebSocket event
    await event_bus.publish(
        Event(
            topic="conversation.transcription",
            tenant_id=tenant_uuid,
            payload={
                "conversation_id": str(conversation_id),
                "message_id": str(message.id),
                "transcription_text": transcription_text,
            },
        )
    )

    return {"status": "ok", "message_id": str(message.id)}


@router.post("/fallback")
async def twilio_fallback(request: Request):
    """Fallback URL -- Twilio calls this if the primary URL fails."""
    return twiml_response(
        f"<Response>{_say_tag('Sorry, we are experiencing difficulties. Please try again later.')}</Response>"
    )
