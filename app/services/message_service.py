"""Service layer for conversation message creation and retrieval."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.message import Message

logger = logging.getLogger(__name__)


class MessageService:
    """Append and list messages within a conversation."""

    async def create_message(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        conversation_id: UUID,
        sender_type: str,
        content: str,
        content_type: str = "text",
        sender_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> Message:
        message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sender_type=sender_type,
            content=content,
            content_type=content_type,
            sender_id=sender_id,
            metadata_=metadata or {},
        )
        db.add(message)
        await db.commit()

        logger.info(
            "Created %s message in conversation %s for tenant %s",
            sender_type,
            conversation_id,
            tenant_id,
        )
        return message

    async def list_messages(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        conversation_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Message]:
        """Return messages for a conversation in chronological order."""
        stmt = (
            select(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation_id,
            )
            .order_by(Message.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())


message_service = MessageService()
