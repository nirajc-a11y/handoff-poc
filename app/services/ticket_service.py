"""Service layer for support ticket management."""

from __future__ import annotations

import logging
import random
import string
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.support_ticket import SupportTicket

logger = logging.getLogger(__name__)


def _generate_ticket_number() -> str:
    """Generate a ticket number in the format TKT-XXXXXX (uppercase alphanumeric)."""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"TKT-{suffix}"


class TicketService:
    """Create and manage support tickets, optionally linked to conversations."""

    async def create_from_conversation(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        conversation_id: UUID,
        subject: str | None = None,
    ) -> SupportTicket:
        """Create a support ticket from an existing conversation."""
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise ValueError(
                f"Conversation not found (id={conversation_id}, tenant_id={tenant_id})"
            )

        ticket_number = _generate_ticket_number()

        ticket = SupportTicket(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            ticket_number=ticket_number,
            customer_identifier=conversation.customer_identifier,
            customer_name=conversation.customer_name,
            subject=subject or f"Support request from {conversation.customer_identifier}",
            status="open",
            priority="medium",
            assigned_agent_id=conversation.current_handler_id,
        )
        db.add(ticket)
        await db.commit()

        logger.info(
            "Created ticket %s from conversation %s for tenant %s",
            ticket_number,
            conversation_id,
            tenant_id,
        )
        return ticket

    async def list_tickets(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        status: str | None = None,
    ) -> list[SupportTicket]:
        stmt = select(SupportTicket).where(
            SupportTicket.tenant_id == tenant_id,
            SupportTicket.is_deleted == False,  # noqa: E712
        )
        if status is not None:
            stmt = stmt.where(SupportTicket.status == status)
        stmt = stmt.order_by(SupportTicket.created_at.desc())

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_ticket(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        ticket_id: UUID,
    ) -> SupportTicket | None:
        stmt = select(SupportTicket).where(
            SupportTicket.id == ticket_id,
            SupportTicket.tenant_id == tenant_id,
            SupportTicket.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_ticket(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        ticket_id: UUID,
        **kwargs,
    ) -> SupportTicket:
        stmt = select(SupportTicket).where(
            SupportTicket.id == ticket_id,
            SupportTicket.tenant_id == tenant_id,
            SupportTicket.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        ticket = result.scalar_one_or_none()
        if ticket is None:
            raise ValueError(
                f"Ticket not found (id={ticket_id}, tenant_id={tenant_id})"
            )

        for key, value in kwargs.items():
            if hasattr(ticket, key):
                setattr(ticket, key, value)

        await db.commit()
        logger.info("Updated ticket %s for tenant %s", ticket_id, tenant_id)
        return ticket


ticket_service = TicketService()
