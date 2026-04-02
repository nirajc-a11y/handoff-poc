"""Agent routing engine -- finds and assigns the best available agent for a conversation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import AgentProfile, AgentStatus

logger = logging.getLogger(__name__)


class RoutingEngine:
    """Least-loaded agent routing with optional skill-based filtering."""

    async def find_available_agent(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        required_skills: list[str] | None = None,
    ) -> UUID | None:
        """Find the best available agent for a tenant.

        Returns the ``AgentProfile.id`` of the least-loaded agent whose status
        is *available* and who has capacity for another conversation, or
        ``None`` if nobody qualifies.

        When *required_skills* is provided the candidate pool is narrowed to
        agents whose ``AgentProfile.skills`` JSONB column contains **any** of
        the requested skills.
        """
        stmt = (
            select(AgentProfile.id)
            .join(AgentStatus, AgentStatus.agent_id == AgentProfile.id)
            .where(
                AgentProfile.tenant_id == tenant_id,
                AgentStatus.status == "available",
                AgentStatus.current_conversations < AgentProfile.max_concurrent,
            )
        )

        if required_skills:
            # PostgreSQL JSONB containment: for each required skill check
            # agent_profiles.skills @> '["skill"]'::jsonb, then OR them.
            from sqlalchemy import or_

            skill_filters = [
                AgentProfile.skills.op("@>")(f'["{skill}"]')
                for skill in required_skills
            ]
            stmt = stmt.where(or_(*skill_filters))

        stmt = stmt.order_by(AgentStatus.current_conversations.asc()).limit(1)

        result = await db.execute(stmt)
        agent_id = result.scalar_one_or_none()

        if agent_id is not None:
            logger.info("Found available agent %s for tenant %s", agent_id, tenant_id)
        else:
            logger.info("No available agent found for tenant %s (skills=%s)", tenant_id, required_skills)

        return agent_id

    async def assign_agent(
        self,
        db: AsyncSession,
        agent_id: UUID,
        tenant_id: UUID,
    ) -> None:
        """Mark an agent as on-call and increment their active conversation count."""
        now = datetime.now(timezone.utc)

        stmt = (
            update(AgentStatus)
            .where(
                AgentStatus.agent_id == agent_id,
                AgentStatus.tenant_id == tenant_id,
            )
            .values(
                status="on_call",
                current_conversations=AgentStatus.current_conversations + 1,
                last_status_change=now,
                updated_at=now,
            )
        )

        await db.execute(stmt)
        await db.flush()
        logger.info("Assigned agent %s for tenant %s", agent_id, tenant_id)

    async def release_agent(
        self,
        db: AsyncSession,
        agent_id: UUID,
        tenant_id: UUID,
    ) -> None:
        """Decrement the agent's active conversation count; set available if idle."""
        now = datetime.now(timezone.utc)

        # First, decrement the counter (ensure it doesn't go below 0)
        stmt = (
            update(AgentStatus)
            .where(
                AgentStatus.agent_id == agent_id,
                AgentStatus.tenant_id == tenant_id,
                AgentStatus.current_conversations > 0,
            )
            .values(
                current_conversations=AgentStatus.current_conversations - 1,
                updated_at=now,
            )
        )
        await db.execute(stmt)
        await db.flush()

        # If current_conversations is now 0, set status back to available
        stmt_available = (
            update(AgentStatus)
            .where(
                AgentStatus.agent_id == agent_id,
                AgentStatus.tenant_id == tenant_id,
                AgentStatus.current_conversations == 0,
            )
            .values(
                status="available",
                last_status_change=now,
                updated_at=now,
            )
        )
        await db.execute(stmt_available)
        await db.flush()
        logger.info("Released agent %s for tenant %s", agent_id, tenant_id)


# Module-level singleton
routing_engine = RoutingEngine()
