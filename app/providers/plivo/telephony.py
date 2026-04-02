"""Plivo telephony provider — wraps the synchronous Plivo SDK for async usage."""

from __future__ import annotations

import asyncio
import logging
import time

import plivo

from app.providers.base import (
    CallEvent,
    CallRequest,
    CallResult,
    CallState,
    TelephonyProvider,
)

logger = logging.getLogger(__name__)

# Plivo call status -> internal CallState mapping
_PLIVO_STATUS_MAP: dict[str, CallState] = {
    "queued": CallState.INITIATED,
    "ringing": CallState.RINGING,
    "in-progress": CallState.ANSWERED,
    "answered": CallState.ANSWERED,
    "completed": CallState.ENDED,
    "busy": CallState.BUSY,
    "no-answer": CallState.NO_ANSWER,
    "failed": CallState.FAILED,
    "canceled": CallState.FAILED,
}


class PlivoTelephonyProvider(TelephonyProvider):
    """Plivo implementation of :class:`TelephonyProvider`.

    The Plivo Python SDK is synchronous, so every SDK call is dispatched to a
    thread via :func:`asyncio.to_thread` to avoid blocking the event loop.
    """

    def __init__(
        self,
        auth_id: str,
        auth_token: str,
        base_webhook_url: str,
    ) -> None:
        self.client = plivo.RestClient(auth_id, auth_token)
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
        """Place an outbound call via Plivo.

        The ``answer_url`` is set to our Plivo answer endpoint so that Plivo
        fetches IVR XML when the callee picks up.  ``status_callback`` receives
        real-time state change notifications.
        """
        tenant_id = str(request.tenant_id)
        answer_url = self._webhook_url(
            "/api/v1/plivo/answer",
            tenant_id=tenant_id,
        )
        fallback_url = self._webhook_url("/api/v1/plivo/fallback")
        status_callback = self._webhook_url(
            "/api/v1/plivo/call-status",
            tenant_id=tenant_id,
        )

        try:
            response = await asyncio.to_thread(
                lambda: self.client.calls.create(
                    from_=request.from_number,
                    to_=request.to_number,
                    answer_url=answer_url,
                    answer_method="POST",
                    hangup_url=status_callback,
                    hangup_method="POST",
                )
            )

            call_uuid = (
                response.request_uuid
                if hasattr(response, "request_uuid")
                else str(response)
            )

            logger.info(
                "Plivo outbound call initiated: %s -> %s (uuid=%s)",
                request.from_number,
                request.to_number,
                call_uuid,
            )

            return CallResult(
                provider_call_id=call_uuid,
                state=CallState.INITIATED,
                metadata={"direction": "outbound", "tenant_id": tenant_id},
            )

        except plivo.exceptions.PlivoRestError as exc:
            logger.error("Plivo initiate_call failed: %s", exc)
            return CallResult(
                provider_call_id="",
                state=CallState.FAILED,
                metadata={"error": str(exc)},
            )

    async def answer_call(
        self, provider_call_id: str, answer_url: str
    ) -> CallResult:
        """For inbound calls, Plivo already fetches the ``answer_url`` XML
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

        * **Cold transfer** -- redirects the call to XML that ``<Dial>``s the
          target number.
        * **Warm transfer** -- places both legs into a shared ``<Conference>``
          so all three parties can speak before the originator drops.
        """
        try:
            if warm:
                # Warm transfer: redirect the customer's call to a conference
                # bridge.  The agent UI would separately dial the target into
                # the same conference room.
                conference_name = f"transfer-{provider_call_id}"
                transfer_xml_url = self._webhook_url(
                    "/api/v1/plivo/connect-agent",
                    conf_name=conference_name,
                )
                await asyncio.to_thread(
                    lambda: self.client.calls.update(
                        provider_call_id,
                        aleg_url=transfer_xml_url,
                        aleg_method="POST",
                    )
                )
            else:
                # Cold transfer: redirect the call to XML that dials the target
                transfer_xml = (
                    f"<Response><Dial><Number>{to_number_or_sip}</Number></Dial></Response>"
                )
                redirect_url = self._webhook_url(
                    "/api/v1/plivo/connect-agent",
                    target=to_number_or_sip,
                )
                await asyncio.to_thread(
                    lambda: self.client.calls.update(
                        provider_call_id,
                        aleg_url=redirect_url,
                        aleg_method="POST",
                    )
                )

            logger.info(
                "Plivo transfer (%s) call %s -> %s",
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

        except plivo.exceptions.PlivoRestError as exc:
            logger.error("Plivo transfer_call failed: %s", exc)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.FAILED,
                metadata={"error": str(exc)},
            )

    async def hold_call(
        self, provider_call_id: str, hold_music_url: str | None = None
    ) -> CallResult:
        """Place the call on hold by redirecting it to XML that loops hold music."""
        try:
            hold_url = self._webhook_url("/api/v1/plivo/hold-music")
            await asyncio.to_thread(
                lambda: self.client.calls.update(
                    provider_call_id,
                    aleg_url=hold_url,
                    aleg_method="POST",
                )
            )

            logger.info("Plivo call %s placed on hold", provider_call_id)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.ON_HOLD,
            )

        except plivo.exceptions.PlivoRestError as exc:
            logger.error("Plivo hold_call failed: %s", exc)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.FAILED,
                metadata={"error": str(exc)},
            )

    async def unhold_call(self, provider_call_id: str) -> CallResult:
        """Resume the call by redirecting it back to a conference bridge."""
        try:
            conference_url = self._webhook_url(
                "/api/v1/plivo/connect-agent",
                conf_name=f"room-{provider_call_id}",
            )
            await asyncio.to_thread(
                lambda: self.client.calls.update(
                    provider_call_id,
                    aleg_url=conference_url,
                    aleg_method="POST",
                )
            )

            logger.info("Plivo call %s resumed from hold", provider_call_id)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.CONNECTED,
            )

        except plivo.exceptions.PlivoRestError as exc:
            logger.error("Plivo unhold_call failed: %s", exc)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.FAILED,
                metadata={"error": str(exc)},
            )

    async def end_call(self, provider_call_id: str) -> CallResult:
        """Hang up the call by deleting (terminating) it via Plivo API."""
        try:
            await asyncio.to_thread(
                lambda: self.client.calls.delete(provider_call_id)
            )

            logger.info("Plivo call %s ended", provider_call_id)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.ENDED,
            )

        except plivo.exceptions.PlivoRestError as exc:
            logger.error("Plivo end_call failed: %s", exc)
            return CallResult(
                provider_call_id=provider_call_id,
                state=CallState.FAILED,
                metadata={"error": str(exc)},
            )

    async def play_audio(
        self, provider_call_id: str, audio_url_or_tts: str
    ) -> None:
        """Play audio or TTS on an active call.

        If the input looks like a URL it is played as audio; otherwise it is
        spoken via Plivo's ``<Speak>`` element by starting a play on the call.
        """
        try:
            if audio_url_or_tts.startswith(("http://", "https://")):
                await asyncio.to_thread(
                    lambda: self.client.calls.play(
                        provider_call_id,
                        urls=[audio_url_or_tts],
                    )
                )
            else:
                await asyncio.to_thread(
                    lambda: self.client.calls.speak(
                        provider_call_id,
                        text=audio_url_or_tts,
                    )
                )

            logger.info(
                "Plivo play_audio on %s: %s",
                provider_call_id,
                audio_url_or_tts[:80],
            )

        except plivo.exceptions.PlivoRestError as exc:
            logger.error("Plivo play_audio failed: %s", exc)

    async def gather_dtmf(
        self,
        provider_call_id: str,
        prompt_url_or_tts: str,
        num_digits: int = 1,
        timeout_seconds: int = 10,
    ) -> str | None:
        """DTMF gathering in Plivo is handled by the ``<GetDigits>`` XML element
        returned in webhook responses, not by a real-time API call.

        This method returns ``None`` to indicate that DTMF collection is driven
        by XML responses in the Plivo webhook endpoints.
        """
        return None

    async def get_call_state(self, provider_call_id: str) -> CallEvent:
        """Poll Plivo for the current state of a call."""
        try:
            call = await asyncio.to_thread(
                lambda: self.client.calls.get(provider_call_id)
            )

            raw_status = getattr(call, "call_status", "unknown").lower()
            state = _PLIVO_STATUS_MAP.get(raw_status, CallState.FAILED)

            duration = getattr(call, "duration", None)
            duration_seconds = int(duration) if duration is not None else None

            return CallEvent(
                provider_call_id=provider_call_id,
                state=state,
                timestamp=time.time(),
                duration_seconds=duration_seconds,
                recording_url=getattr(call, "recording_url", None),
                metadata={
                    "raw_status": raw_status,
                    "direction": getattr(call, "call_direction", None),
                    "from": getattr(call, "from_number", None),
                    "to": getattr(call, "to_number", None),
                },
            )

        except plivo.exceptions.PlivoRestError as exc:
            logger.error("Plivo get_call_state failed for %s: %s", provider_call_id, exc)
            return CallEvent(
                provider_call_id=provider_call_id,
                state=CallState.FAILED,
                timestamp=time.time(),
                metadata={"error": str(exc)},
            )
