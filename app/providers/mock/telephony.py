"""Mock telephony provider for local development and demos."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from uuid import UUID

import httpx

from app.providers.base import (
    CallEvent,
    CallRequest,
    CallResult,
    CallState,
    TelephonyProvider,
)
from app.providers.mock.simulator import generate_mock_id, random_delay

logger = logging.getLogger(__name__)


class MockTelephonyProvider(TelephonyProvider):
    """In-memory telephony simulator.

    Stores all call state in ``_calls`` and optionally fires callback webhooks
    via *httpx* as the call progresses.
    """

    def __init__(self) -> None:
        self._calls: dict[str, dict] = {}
        self._events: dict[str, list[CallEvent]] = {}
        self._scripted_dtmf: dict[str, str] = {}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _set_state(self, call_id: str, state: CallState) -> CallEvent:
        call = self._calls[call_id]
        call["state"] = state
        event = CallEvent(
            provider_call_id=call_id,
            state=state,
            timestamp=time.time(),
            duration_seconds=int(time.time() - call["started_at"]) if state == CallState.ENDED else None,
        )
        self._events.setdefault(call_id, []).append(event)
        return event

    async def _fire_callback(self, call_id: str, event: CallEvent) -> None:
        call = self._calls.get(call_id)
        if not call or not call.get("callback_url"):
            return
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    call["callback_url"],
                    json={
                        "provider_call_id": event.provider_call_id,
                        "state": event.state.value,
                        "timestamp": event.timestamp,
                        "duration_seconds": event.duration_seconds,
                        "recording_url": event.recording_url,
                    },
                )
        except Exception:
            logger.debug("Mock callback failed for call %s (this is expected in tests)", call_id)

    async def _simulate_outbound_progression(self, call_id: str) -> None:
        """Background task that moves an outbound call through states."""
        # INITIATED -> RINGING
        await random_delay(0.3, 0.5)
        if self._calls.get(call_id, {}).get("state") != CallState.INITIATED:
            return
        event = self._set_state(call_id, CallState.RINGING)
        await self._fire_callback(call_id, event)

        # RINGING -> ANSWERED | NO_ANSWER | BUSY (weighted)
        await random_delay(1.0, 4.0)
        if self._calls.get(call_id, {}).get("state") != CallState.RINGING:
            return
        outcome = random.choices(
            [CallState.ANSWERED, CallState.NO_ANSWER, CallState.BUSY],
            weights=[80, 15, 5],
            k=1,
        )[0]
        event = self._set_state(call_id, outcome)
        await self._fire_callback(call_id, event)

    # ------------------------------------------------------------------
    # TelephonyProvider interface
    # ------------------------------------------------------------------

    async def initiate_call(self, request: CallRequest) -> CallResult:
        call_id = generate_mock_id("call")
        self._calls[call_id] = {
            "call_id": call_id,
            "from_number": request.from_number,
            "to_number": request.to_number,
            "tenant_id": str(request.tenant_id),
            "callback_url": request.callback_url,
            "state": CallState.INITIATED,
            "started_at": time.time(),
            "metadata": request.metadata,
        }
        self._set_state(call_id, CallState.INITIATED)

        # Fire-and-forget background progression
        asyncio.create_task(self._simulate_outbound_progression(call_id))

        return CallResult(provider_call_id=call_id, state=CallState.INITIATED)

    async def answer_call(self, provider_call_id: str, answer_url: str) -> CallResult:
        event = self._set_state(provider_call_id, CallState.ANSWERED)
        await self._fire_callback(provider_call_id, event)
        return CallResult(provider_call_id=provider_call_id, state=CallState.ANSWERED)

    async def transfer_call(
        self,
        provider_call_id: str,
        to_number_or_sip: str,
        warm: bool = False,
        announce_url: str | None = None,
    ) -> CallResult:
        if warm:
            await random_delay(1.0, 2.0)
        event = self._set_state(provider_call_id, CallState.TRANSFERRED)
        self._calls[provider_call_id]["transferred_to"] = to_number_or_sip
        await self._fire_callback(provider_call_id, event)
        return CallResult(
            provider_call_id=provider_call_id,
            state=CallState.TRANSFERRED,
            metadata={"transferred_to": to_number_or_sip, "warm": warm},
        )

    async def hold_call(
        self, provider_call_id: str, hold_music_url: str | None = None
    ) -> CallResult:
        event = self._set_state(provider_call_id, CallState.ON_HOLD)
        await self._fire_callback(provider_call_id, event)
        return CallResult(provider_call_id=provider_call_id, state=CallState.ON_HOLD)

    async def unhold_call(self, provider_call_id: str) -> CallResult:
        event = self._set_state(provider_call_id, CallState.CONNECTED)
        await self._fire_callback(provider_call_id, event)
        return CallResult(provider_call_id=provider_call_id, state=CallState.CONNECTED)

    async def end_call(self, provider_call_id: str) -> CallResult:
        event = self._set_state(provider_call_id, CallState.ENDED)
        await self._fire_callback(provider_call_id, event)
        return CallResult(provider_call_id=provider_call_id, state=CallState.ENDED)

    async def play_audio(self, provider_call_id: str, audio_url_or_tts: str) -> None:
        logger.info(
            "Mock play_audio on %s: %s", provider_call_id, audio_url_or_tts
        )

    async def gather_dtmf(
        self,
        provider_call_id: str,
        prompt_url_or_tts: str,
        num_digits: int = 1,
        timeout_seconds: int = 10,
    ) -> str | None:
        scripted = self._scripted_dtmf.pop(provider_call_id, None)
        if scripted is not None:
            return scripted[:num_digits]
        return "1"

    async def get_call_state(self, provider_call_id: str) -> CallEvent:
        events = self._events.get(provider_call_id)
        if events:
            return events[-1]
        call = self._calls.get(provider_call_id)
        if call:
            return CallEvent(
                provider_call_id=provider_call_id,
                state=call["state"],
                timestamp=time.time(),
            )
        return CallEvent(
            provider_call_id=provider_call_id,
            state=CallState.FAILED,
            timestamp=time.time(),
            metadata={"error": "call not found"},
        )

    # ------------------------------------------------------------------
    # Demo / test helpers
    # ------------------------------------------------------------------

    def set_next_dtmf(self, call_id: str, digits: str) -> None:
        """Pre-configure the DTMF response for the next ``gather_dtmf`` call."""
        self._scripted_dtmf[call_id] = digits

    def get_events(self, call_id: str) -> list[CallEvent]:
        """Return all recorded events for a call (useful in tests)."""
        return list(self._events.get(call_id, []))
