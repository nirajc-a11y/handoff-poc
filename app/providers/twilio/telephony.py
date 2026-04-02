"""Twilio telephony provider — wraps the synchronous Twilio SDK for async usage."""

from __future__ import annotations

import asyncio
import logging
import time

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from app.providers.base import (
    CallEvent,
    CallRequest,
    CallResult,
    CallState,
    TelephonyProvider,
)

logger = logging.getLogger(__name__)

# Twilio call status -> internal CallState mapping
_TWILIO_STATUS_MAP: dict[str, CallState] = {
    "queued": CallState.INITIATED,
    "initiated": CallState.INITIATED,
    "ringing": CallState.RINGING,
    "in-progress": CallState.ANSWERED,
    "completed": CallState.ENDED,
    "busy": CallState.BUSY,
    "no-answer": CallState.NO_ANSWER,
    "failed": CallState.FAILED,
    "canceled": CallState.FAILED,
}


class TwilioTelephonyProvider(TelephonyProvider):
    """Twilio implementation of :class:`TelephonyProvider`.

    The Twilio Python SDK is synchronous, so every SDK call is dispatched to a
    thread via :func:`asyncio.to_thread` to avoid blocking the event loop.
    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        base_webhook_url: str,
    ) -> None:
        self.client = Client(account_sid, auth_token)
        self.base_webhook_url = base_webhook_url.rstrip("/")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _webhook_url(self, path: str, **params: str) -> str:
        """Build an absolute webhook URL with optional query parameters."""
        url = f"{self.base_webhook_url}{path}"
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items() if v)
            url = f"{url}?{qs}"
        return url

    # ------------------------------------------------------------------
    # TelephonyProvider interface
    # ------------------------------------------------------------------

    async def initiate_call(self, request: CallRequest) -> CallResult:
        """Place an outbound call via Twilio.

        The ``url`` parameter tells Twilio where to fetch TwiML when the
        callee picks up.  ``status_callback`` receives real-time state
        change notifications.
        """
        tenant_id = str(request.tenant_id)
        answer_url = self._webhook_url(
            "/api/v1/twilio/answer",
            tenant_id=tenant_id,
        )
        fallback_url = self._webhook_url("/api/v1/twilio/fallback")
        status_callback = self._webhook_url(
            "/api/v1/twilio/call-status",
            tenant_id=tenant_id,
        )

        try:
            call = await asyncio.to_thread(
                lambda: self.client.calls.create(
                    from_=request.from_number,
                    to=request.to_number,
                    url=answer_url,
                    method="POST",
                    fallback_url=fallback_url,
                    fallback_method="POST",
                    status_callback=status_callback,
                    status_callback_method="POST",
                    status_callback_event=[
                        "initiated",
                        "ringing",
                        "answered",
                        "completed",
                    ],
                )
            )

            call_sid = call.sid

            logger.info(
                "Twilio outbound call initiated: %s -> %s (sid=%s)",
                request.from_number,
                request.to_number,
                call_sid,
            )

            return CallResult(
                provider_call_id=call_sid,
                state=CallState.INITIATED,
                metadata={"direction": "outbound", "tenant_id": tenant_id},
            )

        except TwilioRestException as exc:
            logger.error("Twilio initiate_call failed: %s", exc)
            return CallResult(
                provider_call_id="",
                state=CallState.FAILED,
                metadata={"error": str(exc)},
            )

    async def answer_call(
        self, provider_call_id: str, answer_url: str
    ) -> CallResult:
        """For inbound calls, Twilio already fetches the ``url`` TwiML
        when the call arrives, so this is effectively a no-op.  We simply
        return the current call state.
        """
        event = await self.get_call_state(provider_call_id)
        return CallResult(
            provider_call_id=provider_call_id,
            state=event.state,
            metadata=event.metadata,
        )

    async def transfer_call(
        self,
        provider_call_id: str,
        to_number_or_sip: str,
        warm: bool = False,
        announce_url: str | None = None,
    ) -> CallResult:
        """Transfer a live call.

        * **Cold transfer** -- updates the call with TwiML that ``<Dial>``s
          the target number.
        * **Warm transfer** -- redirects the customer into a shared
          ``<Conference>`` so all three parties can speak before the
          originator drops.
        """
        try:
            if warm:
                # Warm transfer: redirect the customer's call to a conference
                # bridge.  The agent UI would separately dial the target into
                # the same conference room.
                conference_name = f"transfer-{provider_call_id}"
                transfer_url = self._webhook_url(
                    "/api/v1/twilio/connect-agent",
                    conf_name=conference_name,
                )
                await asyncio.to_thread(
                    lambda: self.client.calls(provider_call_id).update(
                        url=transfer_url,
                        method="POST",
                    )
                )
            else:
                # Cold transfer: redirect the call to TwiML that dials the target
                redirect_url = self._webhook_url(
                    "/api/v1/twilio/connect-agent",
                    target=to_number_or_sip,
                )
                await asyncio.to_thread(
                    lambda: self.client.calls(provider_call_id).update(
                        url=redirect_url,
                        method="POST",
                    )
                )

            logger.info(
                "Twilio transfer (%s) call %s -> %s",
                "warm" if warm else "cold",
                provider_call_id,
                to_number_or_sip,
            )

            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.TRANSFERRED,
                metadata={
                    "transferred_to": to_number_or_sip,
                    "warm": warm,
                },
            )

        except TwilioRestException as exc:
            logger.error("Twilio transfer_call failed: %s", exc)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.FAILED,
                metadata={"error": str(exc)},
            )

    async def hold_call(
        self, provider_call_id: str, hold_music_url: str | None = None
    ) -> CallResult:
        """Place the call on hold by redirecting it to TwiML that loops hold music."""
        try:
            hold_url = self._webhook_url("/api/v1/twilio/hold-music")
            await asyncio.to_thread(
                lambda: self.client.calls(provider_call_id).update(
                    url=hold_url,
                    method="POST",
                )
            )

            logger.info("Twilio call %s placed on hold", provider_call_id)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.ON_HOLD,
            )

        except TwilioRestException as exc:
            logger.error("Twilio hold_call failed: %s", exc)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.FAILED,
                metadata={"error": str(exc)},
            )

    async def unhold_call(self, provider_call_id: str) -> CallResult:
        """Resume the call by redirecting it back to a conference bridge."""
        try:
            conference_url = self._webhook_url(
                "/api/v1/twilio/connect-agent",
                conf_name=f"room-{provider_call_id}",
            )
            await asyncio.to_thread(
                lambda: self.client.calls(provider_call_id).update(
                    url=conference_url,
                    method="POST",
                )
            )

            logger.info("Twilio call %s resumed from hold", provider_call_id)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.CONNECTED,
            )

        except TwilioRestException as exc:
            logger.error("Twilio unhold_call failed: %s", exc)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.FAILED,
                metadata={"error": str(exc)},
            )

    async def end_call(self, provider_call_id: str) -> CallResult:
        """Hang up the call by updating its status to ``completed``."""
        try:
            await asyncio.to_thread(
                lambda: self.client.calls(provider_call_id).update(
                    status="completed",
                )
            )

            logger.info("Twilio call %s ended", provider_call_id)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.ENDED,
            )

        except TwilioRestException as exc:
            logger.error("Twilio end_call failed: %s", exc)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.FAILED,
                metadata={"error": str(exc)},
            )

    async def play_audio(
        self, provider_call_id: str, audio_url_or_tts: str
    ) -> None:
        """Play audio or TTS on an active call.

        If the input looks like a URL it is played as audio via ``<Play>``;
        otherwise it is spoken via Twilio's ``<Say>`` element by updating
        the call with inline TwiML.
        """
        try:
            if audio_url_or_tts.startswith(("http://", "https://")):
                twiml = (
                    f"<Response><Play>{audio_url_or_tts}</Play></Response>"
                )
            else:
                escaped = _escape_xml(audio_url_or_tts)
                twiml = f"<Response><Say>{escaped}</Say></Response>"

            await asyncio.to_thread(
                lambda: self.client.calls(provider_call_id).update(
                    twiml=twiml,
                )
            )

            logger.info(
                "Twilio play_audio on %s: %s",
                provider_call_id,
                audio_url_or_tts[:80],
            )

        except TwilioRestException as exc:
            logger.error("Twilio play_audio failed: %s", exc)

    async def gather_dtmf(
        self,
        provider_call_id: str,
        prompt_url_or_tts: str,
        num_digits: int = 1,
        timeout_seconds: int = 10,
    ) -> str | None:
        """DTMF gathering in Twilio is handled by the ``<Gather>`` TwiML verb
        returned in webhook responses, not by a real-time API call.

        This method returns ``None`` to indicate that DTMF collection is driven
        by TwiML responses in the Twilio webhook endpoints.
        """
        return None

    async def get_call_state(self, provider_call_id: str) -> CallEvent:
        """Poll Twilio for the current state of a call."""
        try:
            call = await asyncio.to_thread(
                lambda: self.client.calls(provider_call_id).fetch()
            )

            raw_status = (call.status or "unknown").lower()
            state = _TWILIO_STATUS_MAP.get(raw_status, CallState.FAILED)

            duration = call.duration
            duration_seconds = int(duration) if duration is not None else None

            return CallEvent(
                provider_call_id=provider_call_id,
                state=state,
                timestamp=time.time(),
                duration_seconds=duration_seconds,
                metadata={
                    "raw_status": raw_status,
                    "direction": call.direction,
                    "from": call.from_formatted,
                    "to": call.to_formatted,
                },
            )

        except TwilioRestException as exc:
            logger.error(
                "Twilio get_call_state failed for %s: %s",
                provider_call_id,
                exc,
            )
            return CallEvent(
                provider_call_id=provider_call_id,
                state=CallState.FAILED,
                timestamp=time.time(),
                metadata={"error": str(exc)},
            )


def _escape_xml(text: str) -> str:
    """Escape special XML characters in user-provided text."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
