"""Mock SMS provider for local development and demos."""

from __future__ import annotations

import logging
import time
from uuid import UUID

from app.providers.base import SMSMessage, SMSProvider, SMSResult
from app.providers.mock.simulator import generate_mock_id

logger = logging.getLogger(__name__)


class MockSMSProvider(SMSProvider):
    """In-memory SMS simulator that stores all sent messages for inspection."""

    def __init__(self) -> None:
        self._messages: list[dict] = []

    async def send_sms(
        self, tenant_id: UUID, message: SMSMessage
    ) -> SMSResult:
        msg_id = generate_mock_id("sms")
        record = {
            "provider_message_id": msg_id,
            "tenant_id": str(tenant_id),
            "to_number": message.to_number,
            "from_number": message.from_number,
            "body": message.body,
            "timestamp": time.time(),
            "status": "sent",
        }
        self._messages.append(record)
        logger.info("Mock SMS %s -> %s", msg_id, message.to_number)
        return SMSResult(
            provider_message_id=msg_id,
            status="sent",
            metadata={"mock": True},
        )

    async def parse_webhook(self, payload: dict) -> dict:
        return {
            "provider": "mock",
            "from_number": payload.get("from"),
            "to_number": payload.get("to"),
            "body": payload.get("text", ""),
            "timestamp": time.time(),
            "raw": payload,
        }

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def get_messages(self) -> list[dict]:
        """Return all stored messages (useful in tests)."""
        return list(self._messages)
