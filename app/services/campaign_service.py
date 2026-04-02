"""Service layer for campaign and campaign-lead management."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.campaign import Campaign, CampaignLead

logger = logging.getLogger(__name__)


class CampaignService:
    """CRUD and lead-assignment operations for campaigns."""

    async def create_campaign(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        name: str,
        type: str,
        config: dict | None = None,
        created_by: UUID | None = None,
    ) -> Campaign:
        campaign = Campaign(
            tenant_id=tenant_id,
            name=name,
            type=type,
            config=config or {},
            created_by=created_by,
        )
        db.add(campaign)
        await db.commit()
        logger.info("Created campaign '%s' (%s) for tenant %s", name, campaign.id, tenant_id)
        return campaign

    async def list_campaigns(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        status: str | None = None,
    ) -> list[Campaign]:
        stmt = select(Campaign).where(
            Campaign.tenant_id == tenant_id,
            Campaign.is_deleted == False,  # noqa: E712
        )
        if status is not None:
            stmt = stmt.where(Campaign.status == status)
        stmt = stmt.order_by(Campaign.created_at.desc())

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_campaign(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
    ) -> Campaign | None:
        stmt = select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
            Campaign.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_campaign(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
        **kwargs,
    ) -> Campaign:
        stmt = select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
            Campaign.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        campaign = result.scalar_one_or_none()
        if campaign is None:
            raise ValueError(
                f"Campaign not found (id={campaign_id}, tenant_id={tenant_id})"
            )

        for key, value in kwargs.items():
            if hasattr(campaign, key):
                setattr(campaign, key, value)

        await db.commit()
        logger.info("Updated campaign %s for tenant %s", campaign_id, tenant_id)
        return campaign

    async def delete_campaign(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
    ) -> None:
        """Soft-delete a campaign."""
        stmt = select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
            Campaign.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        campaign = result.scalar_one_or_none()
        if campaign is None:
            raise ValueError(
                f"Campaign not found (id={campaign_id}, tenant_id={tenant_id})"
            )

        campaign.is_deleted = True
        campaign.deleted_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info("Soft-deleted campaign %s for tenant %s", campaign_id, tenant_id)

    async def add_leads(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
        lead_ids: list[UUID],
    ) -> list[CampaignLead]:
        """Attach leads to a campaign. Returns the created CampaignLead rows."""
        campaign_leads: list[CampaignLead] = []
        for lead_id in lead_ids:
            cl = CampaignLead(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                lead_id=lead_id,
            )
            db.add(cl)
            campaign_leads.append(cl)

        await db.commit()
        logger.info(
            "Added %d leads to campaign %s for tenant %s",
            len(lead_ids),
            campaign_id,
            tenant_id,
        )
        return campaign_leads

    async def list_campaign_leads(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
        status: str | None = None,
    ) -> list[CampaignLead]:
        stmt = select(CampaignLead).where(
            CampaignLead.tenant_id == tenant_id,
            CampaignLead.campaign_id == campaign_id,
        )
        if status is not None:
            stmt = stmt.where(CampaignLead.status == status)
        stmt = stmt.order_by(CampaignLead.created_at.asc())

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def assign_leads(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
        agent_id: UUID,
        count: int = 10,
    ) -> int:
        """Assign up to *count* unassigned pending leads to *agent_id*. Returns number assigned."""
        # Find ids of unassigned pending leads
        sub = (
            select(CampaignLead.id)
            .where(
                CampaignLead.tenant_id == tenant_id,
                CampaignLead.campaign_id == campaign_id,
                CampaignLead.status == "pending",
                CampaignLead.assigned_agent_id.is_(None),
            )
            .order_by(CampaignLead.created_at.asc())
            .limit(count)
        )
        id_result = await db.execute(sub)
        ids_to_assign = list(id_result.scalars().all())

        if not ids_to_assign:
            return 0

        stmt = (
            update(CampaignLead)
            .where(CampaignLead.id.in_(ids_to_assign))
            .values(assigned_agent_id=agent_id)
        )
        await db.execute(stmt)
        await db.commit()

        logger.info(
            "Assigned %d leads in campaign %s to agent %s (tenant %s)",
            len(ids_to_assign),
            campaign_id,
            agent_id,
            tenant_id,
        )
        return len(ids_to_assign)

    async def get_next_lead(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
        agent_id: UUID,
    ) -> CampaignLead | None:
        """Get the next pending lead assigned to this agent, ordered by created_at."""
        stmt = (
            select(CampaignLead)
            .where(
                CampaignLead.tenant_id == tenant_id,
                CampaignLead.campaign_id == campaign_id,
                CampaignLead.assigned_agent_id == agent_id,
                CampaignLead.status == "pending",
            )
            .order_by(CampaignLead.created_at.asc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


campaign_service = CampaignService()
