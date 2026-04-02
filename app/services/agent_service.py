"""Service layer for agent profiles and status management."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.conversation import Conversation
from app.db.models.user import AgentProfile, AgentStatus

logger = logging.getLogger(__name__)


class AgentService:
    """Agent listing, status updates, and stat queries."""

    async def list_agents(
        self,
        db: AsyncSession,
        tenant_id: UUID,
    ) -> list[AgentProfile]:
        """Return all agent profiles for the tenant, eagerly loading their status."""
        stmt = (
            select(AgentProfile)
            .where(AgentProfile.tenant_id == tenant_id)
            .options(selectinload(AgentProfile.status))
            .order_by(AgentProfile.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_agent(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        agent_id: UUID,
    ) -> AgentProfile | None:
        stmt = (
            select(AgentProfile)
            .where(
                AgentProfile.id == agent_id,
                AgentProfile.tenant_id == tenant_id,
            )
            .options(selectinload(AgentProfile.status))
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        agent_id: UUID,
        status: str,
    ) -> AgentStatus:
        """Update an agent's status and record the timestamp of the change."""
        stmt = select(AgentStatus).where(
            AgentStatus.agent_id == agent_id,
            AgentStatus.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        agent_status = result.scalar_one_or_none()
        if agent_status is None:
            raise ValueError(
                f"AgentStatus not found (agent_id={agent_id}, tenant_id={tenant_id})"
            )

        now = datetime.now(timezone.utc)
        agent_status.status = status
        agent_status.last_status_change = now
        agent_status.updated_at = now
        await db.commit()

        logger.info(
            "Updated agent %s status to '%s' for tenant %s",
            agent_id,
            status,
            tenant_id,
        )
        return agent_status

    async def get_available_agents(
        self,
        db: AsyncSession,
        tenant_id: UUID,
    ) -> list[AgentProfile]:
        """Return agents whose current status is 'available'."""
        stmt = (
            select(AgentProfile)
            .join(AgentStatus, AgentStatus.agent_id == AgentProfile.id)
            .where(
                AgentProfile.tenant_id == tenant_id,
                AgentStatus.status == "available",
            )
            .options(selectinload(AgentProfile.status))
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_agent_stats(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        agent_id: UUID,
    ) -> dict:
        """Count conversations by state for this agent today."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )

        stmt = (
            select(Conversation.state, func.count(Conversation.id))
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.current_handler_id == agent_id,
                Conversation.created_at >= today_start,
            )
            .group_by(Conversation.state)
        )
        result = await db.execute(stmt)
        rows = result.all()

        stats: dict = {
            "total": 0,
            "by_state": {},
        }
        for state, count in rows:
            stats["by_state"][state] = count
            stats["total"] += count

        return stats


agent_service = AgentService()
