"""Mock WhatsApp provider for local development and demos."""

from __future__ import annotations

import logging
import time
from uuid import UUID

from app.providers.base import WhatsAppMessage, WhatsAppMessageResult, WhatsAppProvider
from app.providers.mock.simulator import generate_mock_id

logger = logging.getLogger(__name__)


class MockWhatsAppProvider(WhatsAppProvider):
    """In-memory WhatsApp simulator that stores all messages for inspection."""

    def __init__(self) -> None:
        self._messages: list[dict] = []

    async def send_message(
        self, tenant_id: UUID, message: WhatsAppMessage
    ) -> WhatsAppMessageResult:
        msg_id = generate_mock_id("wa")
        record = {
            "provider_message_id": msg_id,
            "tenant_id": str(tenant_id),
            "to_number": message.to_number,
            "content": message.content,
            "content_type": message.content_type,
            "media_url": message.media_url,
            "timestamp": time.time(),
            "status": "delivered",
        }
        self._messages.append(record)
        logger.info("Mock WhatsApp message %s -> %s", msg_id, message.to_number)
        return WhatsAppMessageResult(
            provider_message_id=msg_id,
            status="delivered",
            metadata={"mock": True},
        )

    async def send_template(
        self, tenant_id: UUID, message: WhatsAppMessage
    ) -> WhatsAppMessageResult:
        msg_id = generate_mock_id("wa-tpl")
        record = {
            "provider_message_id": msg_id,
            "tenant_id": str(tenant_id),
            "to_number": message.to_number,
            "template_name": message.template_name,
            "template_params": message.template_params,
            "timestamp": time.time(),
            "status": "delivered",
        }
        self._messages.append(record)
        logger.info("Mock WhatsApp template %s -> %s", msg_id, message.to_number)
        return WhatsAppMessageResult(
            provider_message_id=msg_id,
            status="delivered",
            metadata={"mock": True, "template_name": message.template_name},
        )

    async def mark_read(
        self, tenant_id: UUID, provider_message_id: str
    ) -> None:
        for msg in self._messages:
            if msg["provider_message_id"] == provider_message_id:
                msg["status"] = "read"
                break
        logger.info("Mock WhatsApp mark_read: %s", provider_message_id)

    async def parse_webhook(self, payload: dict) -> dict:
        return {
            "provider": "mock",
            "type": payload.get("type", "message"),
            "from_number": payload.get("from"),
            "content": payload.get("text", ""),
            "timestamp": time.time(),
            "raw": payload,
        }

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def get_messages(self) -> list[dict]:
        """Return all stored messages (useful in tests)."""
        return list(self._messages)
