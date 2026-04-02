"""Service layer for voice call lifecycle management."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.config import settings
from app.db.models.channel_session import ChannelSession
from app.db.models.conversation import Conversation
from app.db.models.tenant import Tenant
from app.providers.base import CallRequest
from app.providers.registry import provider_registry

logger = logging.getLogger(__name__)


def _get_from_number(provider_name: str) -> str:
    """Return the caller-ID phone number for the given provider."""
    if provider_name == "plivo" and settings.plivo_number:
        return settings.plivo_number
    if provider_name == "twilio" and settings.twilio_number:
        return settings.twilio_number
    return "system"


async def _get_provider_name(db: AsyncSession, tenant_id: UUID) -> str:
    """Read tenant config to determine which telephony provider to use."""
    result = await db.execute(
        select(Tenant.config).where(Tenant.id == tenant_id)
    )
    config = result.scalar_one_or_none()
    if config and isinstance(config, dict):
        return config.get("providers", {}).get("telephony", "mock")
    return "mock"


class CallService:
    """Manages outbound / inbound voice call creation and lookup."""

    async def initiate_outbound_call(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        agent_id: UUID,
        to_number: str,
        customer_name: str | None = None,
        lead_id: UUID | None = None,
        campaign_lead_id: UUID | None = None,
    ) -> Conversation:
        """Create a conversation + channel session and place an outbound call via the provider."""
        now = datetime.now(timezone.utc)

        conversation = Conversation(
            tenant_id=tenant_id,
            channel="voice",
            direction="outbound",
            state="initiated",
            customer_identifier=to_number,
            customer_name=customer_name,
            lead_id=lead_id,
            campaign_lead_id=campaign_lead_id,
            current_handler_type="human",
            current_handler_id=agent_id,
            started_at=now,
        )
        db.add(conversation)
        await db.flush()

        # Determine provider and from-number from tenant config
        provider_name = await _get_provider_name(db, tenant_id)
        from_number = _get_from_number(provider_name)

        channel_session = ChannelSession(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            channel="voice",
            provider=provider_name,
            provider_session_id="",  # placeholder until provider returns id
            direction="outbound",
            from_address=from_number,
            to_address=to_number,
            started_at=now,
        )
        db.add(channel_session)
        await db.flush()

        # Initiate the call via the telephony provider
        provider = await provider_registry.get_telephony(tenant_id, db)
        call_result = await provider.initiate_call(
            CallRequest(
                from_number=from_number,
                to_number=to_number,
                tenant_id=tenant_id,
                callback_url="",
                metadata={"conversation_id": str(conversation.id)},
            )
        )

        # Store the provider-assigned session id
        channel_session.provider_session_id = call_result.provider_call_id
        await db.commit()

        logger.info(
            "Initiated outbound call %s for tenant %s (provider_call_id=%s)",
            conversation.id,
            tenant_id,
            call_result.provider_call_id,
        )
        return conversation

    async def handle_inbound_call(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        from_number: str,
        to_number: str,
        provider_call_id: str,
        customer_name: str | None = None,
    ) -> Conversation:
        """Record an inbound call that arrived from the provider webhook."""
        now = datetime.now(timezone.utc)

        conversation = Conversation(
            tenant_id=tenant_id,
            channel="voice",
            direction="inbound",
            state="initiated",
            customer_identifier=from_number,
            customer_name=customer_name,
            current_handler_type="system",
            started_at=now,
        )
        db.add(conversation)
        await db.flush()

        channel_session = ChannelSession(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            channel="voice",
            provider="mock",
            provider_session_id=provider_call_id,
            direction="inbound",
            from_address=from_number,
            to_address=to_number,
            started_at=now,
        )
        db.add(channel_session)
        await db.commit()

        logger.info(
            "Recorded inbound call %s for tenant %s (provider_call_id=%s)",
            conversation.id,
            tenant_id,
            provider_call_id,
        )
        return conversation

    async def get_call(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        conversation_id: UUID,
    ) -> Conversation | None:
        """Retrieve a voice conversation by id and tenant."""
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.channel == "voice",
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


call_service = CallService()
