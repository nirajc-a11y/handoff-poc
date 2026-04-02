"""Abstract base classes and data types for all channel providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID


# ---------------------------------------------------------------------------
# Telephony
# ---------------------------------------------------------------------------

class CallState(str, Enum):
    INITIATED = "initiated"
    RINGING = "ringing"
    ANSWERED = "answered"
    CONNECTED = "connected"
    ON_HOLD = "on_hold"
    TRANSFERRED = "transferred"
    ENDED = "ended"
    FAILED = "failed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"


@dataclass
class CallRequest:
    from_number: str
    to_number: str
    tenant_id: UUID
    callback_url: str
    metadata: dict | None = None


@dataclass
class CallResult:
    provider_call_id: str
    state: CallState
    metadata: dict | None = None


@dataclass
class CallEvent:
    provider_call_id: str
    state: CallState
    timestamp: float
    duration_seconds: int | None = None
    recording_url: str | None = None
    metadata: dict | None = None


class TelephonyProvider(ABC):
    @abstractmethod
    async def initiate_call(self, request: CallRequest) -> CallResult: ...

    @abstractmethod
    async def answer_call(self, provider_call_id: str, answer_url: str) -> CallResult: ...

    @abstractmethod
    async def transfer_call(
        self,
        provider_call_id: str,
        to_number_or_sip: str,
        warm: bool = False,
        announce_url: str | None = None,
    ) -> CallResult: ...

    @abstractmethod
    async def hold_call(
        self, provider_call_id: str, hold_music_url: str | None = None
    ) -> CallResult: ...

    @abstractmethod
    async def unhold_call(self, provider_call_id: str) -> CallResult: ...

    @abstractmethod
    async def end_call(self, provider_call_id: str) -> CallResult: ...

    @abstractmethod
    async def play_audio(self, provider_call_id: str, audio_url_or_tts: str) -> None: ...

    @abstractmethod
    async def gather_dtmf(
        self,
        provider_call_id: str,
        prompt_url_or_tts: str,
        num_digits: int = 1,
        timeout_seconds: int = 10,
    ) -> str | None: ...

    @abstractmethod
    async def get_call_state(self, provider_call_id: str) -> CallEvent: ...


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------

@dataclass
class WhatsAppMessage:
    to_number: str
    content: str
    content_type: str = "text"
    media_url: str | None = None
    template_name: str | None = None
    template_params: dict | None = None
    metadata: dict | None = None


@dataclass
class WhatsAppMessageResult:
    provider_message_id: str
    status: str
    metadata: dict | None = None


class WhatsAppProvider(ABC):
    @abstractmethod
    async def send_message(
        self, tenant_id: UUID, message: WhatsAppMessage
    ) -> WhatsAppMessageResult: ...

    @abstractmethod
    async def send_template(
        self, tenant_id: UUID, message: WhatsAppMessage
    ) -> WhatsAppMessageResult: ...

    @abstractmethod
    async def mark_read(
        self, tenant_id: UUID, provider_message_id: str
    ) -> None: ...

    @abstractmethod
    async def parse_webhook(self, payload: dict) -> dict: ...


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

@dataclass
class EmailMessage:
    to: list[str]
    subject: str
    body_html: str
    body_text: str | None = None
    from_address: str | None = None
    cc: list[str] | None = None
    bcc: list[str] | None = None
    reply_to: str | None = None
    in_reply_to: str | None = None
    references: list[str] | None = None
    attachments: list[dict] | None = None
    metadata: dict | None = None


@dataclass
class EmailResult:
    provider_message_id: str
    message_id_header: str
    status: str
    metadata: dict | None = None


class EmailProvider(ABC):
    @abstractmethod
    async def send_email(
        self, tenant_id: UUID, email: EmailMessage
    ) -> EmailResult: ...

    @abstractmethod
    async def parse_inbound_webhook(self, payload: dict) -> dict: ...


# ---------------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------------

@dataclass
class SMSMessage:
    to_number: str
    body: str
    from_number: str | None = None
    metadata: dict | None = None


@dataclass
class SMSResult:
    provider_message_id: str
    status: str
    metadata: dict | None = None


class SMSProvider(ABC):
    @abstractmethod
    async def send_sms(
        self, tenant_id: UUID, message: SMSMessage
    ) -> SMSResult: ...

    @abstractmethod
    async def parse_webhook(self, payload: dict) -> dict: ...
