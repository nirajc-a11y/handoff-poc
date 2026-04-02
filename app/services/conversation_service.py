"""Service layer for conversation CRUD and queries."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.conversation import Conversation

logger = logging.getLogger(__name__)


class ConversationService:
    """Read / update operations on conversations across all channels."""

    async def list_conversations(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        state: str | None = None,
        channel: str | None = None,
        handler_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        """Return conversations with optional filters, newest first."""
        stmt = select(Conversation).where(Conversation.tenant_id == tenant_id)

        if state is not None:
            stmt = stmt.where(Conversation.state == state)
        if channel is not None:
            stmt = stmt.where(Conversation.channel == channel)
        if handler_id is not None:
            stmt = stmt.where(Conversation.current_handler_id == handler_id)

        stmt = stmt.order_by(Conversation.created_at.desc()).limit(limit).offset(offset)

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_conversation(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        conversation_id: UUID,
    ) -> Conversation | None:
        """Load a single conversation with its messages, handoff events, and channel sessions."""
        stmt = (
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
            .options(
                selectinload(Conversation.messages),
                selectinload(Conversation.handoff_events),
                selectinload(Conversation.channel_sessions),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_conversations(
        self,
        db: AsyncSession,
        tenant_id: UUID,
    ) -> list[Conversation]:
        """Return all conversations that have not ended or failed."""
        stmt = (
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.state.notin_(["ended", "failed"]),
            )
            .order_by(Conversation.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def set_disposition(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        conversation_id: UUID,
        disposition: str,
        notes: str | None = None,
    ) -> Conversation:
        """Set disposition and optional notes on a conversation."""
        stmt = (
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise ValueError(
                f"Conversation not found (id={conversation_id}, tenant_id={tenant_id})"
            )

        conversation.disposition = disposition
        if notes is not None:
            conversation.disposition_notes = notes

        await db.commit()

        logger.info(
            "Set disposition '%s' on conversation %s for tenant %s",
            disposition,
            conversation_id,
            tenant_id,
        )
        return conversation


conversation_service = ConversationService()
