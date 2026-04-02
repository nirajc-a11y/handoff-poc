"""Mock email provider for local development and demos."""

from __future__ import annotations

import logging
import time
from uuid import UUID

from app.providers.base import EmailMessage, EmailProvider, EmailResult
from app.providers.mock.simulator import generate_mock_id

logger = logging.getLogger(__name__)


class MockEmailProvider(EmailProvider):
    """In-memory email simulator that stores all sent emails for inspection."""

    def __init__(self) -> None:
        self._emails: list[dict] = []

    async def send_email(
        self, tenant_id: UUID, email: EmailMessage
    ) -> EmailResult:
        msg_id = generate_mock_id("email")
        message_id_header = f"<{msg_id}@mock.angeltel.local>"
        record = {
            "provider_message_id": msg_id,
            "message_id_header": message_id_header,
            "tenant_id": str(tenant_id),
            "to": email.to,
            "subject": email.subject,
            "from_address": email.from_address,
            "cc": email.cc,
            "bcc": email.bcc,
            "reply_to": email.reply_to,
            "in_reply_to": email.in_reply_to,
            "references": email.references,
            "has_attachments": bool(email.attachments),
            "timestamp": time.time(),
            "status": "sent",
        }
        self._emails.append(record)
        logger.info("Mock email %s -> %s: %s", msg_id, email.to, email.subject)
        return EmailResult(
            provider_message_id=msg_id,
            message_id_header=message_id_header,
            status="sent",
            metadata={"mock": True},
        )

    async def parse_inbound_webhook(self, payload: dict) -> dict:
        return {
            "provider": "mock",
            "from_address": payload.get("from"),
            "to": payload.get("to", []),
            "subject": payload.get("subject", ""),
            "body_text": payload.get("text", ""),
            "body_html": payload.get("html", ""),
            "timestamp": time.time(),
            "raw": payload,
        }

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def get_emails(self) -> list[dict]:
        """Return all stored emails (useful in tests)."""
        return list(self._emails)
