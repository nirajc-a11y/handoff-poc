"""Campaign endpoints."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_tenant_id
from app.services.campaign_service import campaign_service

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CampaignCreate(BaseModel):
    name: str
    type: str
    config: dict | None = None
    start_date: date | None = None
    end_date: date | None = None


class CampaignUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    config: dict | None = None


class AddLeads(BaseModel):
    lead_ids: list[UUID]


class AssignLeads(BaseModel):
    agent_id: UUID
    count: int = 10


class NextLead(BaseModel):
    agent_id: UUID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _campaign_dict(c) -> dict:
    return {
        "id": str(c.id),
        "tenant_id": str(c.tenant_id),
        "name": c.name,
        "type": c.type,
        "status": c.status,
        "start_date": str(c.start_date) if c.start_date else None,
        "end_date": str(c.end_date) if c.end_date else None,
        "config": c.config,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _campaign_lead_dict(cl) -> dict:
    return {
        "id": str(cl.id),
        "campaign_id": str(cl.campaign_id),
        "lead_id": str(cl.lead_id),
        "assigned_agent_id": str(cl.assigned_agent_id) if cl.assigned_agent_id else None,
        "status": cl.status,
        "attempt_count": cl.attempt_count,
        "last_attempt_at": cl.last_attempt_at.isoformat() if cl.last_attempt_at else None,
        "next_retry_at": cl.next_retry_at.isoformat() if cl.next_retry_at else None,
        "disposition": cl.disposition,
        "notes": cl.notes,
        "created_at": cl.created_at.isoformat() if cl.created_at else None,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("")
async def create_campaign(
    body: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    campaign = await campaign_service.create_campaign(
        db,
        tenant_id=tenant_id,
        name=body.name,
        type=body.type,
        config=body.config,
    )
    return _campaign_dict(campaign)


@router.get("")
async def list_campaigns(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    campaigns = await campaign_service.list_campaigns(db, tenant_id=tenant_id, status=status)
    return [_campaign_dict(c) for c in campaigns]


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    campaign = await campaign_service.get_campaign(db, tenant_id=tenant_id, campaign_id=campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _campaign_dict(campaign)


@router.patch("/{campaign_id}")
async def update_campaign(
    campaign_id: UUID,
    body: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        campaign = await campaign_service.update_campaign(
            db, tenant_id=tenant_id, campaign_id=campaign_id, **updates
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _campaign_dict(campaign)


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    try:
        await campaign_service.delete_campaign(db, tenant_id=tenant_id, campaign_id=campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"detail": "Campaign deleted"}


@router.post("/{campaign_id}/leads")
async def add_leads(
    campaign_id: UUID,
    body: AddLeads,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    # Verify campaign exists first
    campaign = await campaign_service.get_campaign(db, tenant_id=tenant_id, campaign_id=campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign_leads = await campaign_service.add_leads(
        db, tenant_id=tenant_id, campaign_id=campaign_id, lead_ids=body.lead_ids
    )
    return {"added": len(campaign_leads), "campaign_leads": [_campaign_lead_dict(cl) for cl in campaign_leads]}


@router.get("/{campaign_id}/leads")
async def list_campaign_leads(
    campaign_id: UUID,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    leads = await campaign_service.list_campaign_leads(
        db, tenant_id=tenant_id, campaign_id=campaign_id, status=status
    )
    return [_campaign_lead_dict(cl) for cl in leads]


@router.post("/{campaign_id}/assign")
async def assign_leads(
    campaign_id: UUID,
    body: AssignLeads,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    assigned = await campaign_service.assign_leads(
        db,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        agent_id=body.agent_id,
        count=body.count,
    )
    return {"assigned": assigned}


@router.post("/{campaign_id}/next-lead")
async def next_lead(
    campaign_id: UUID,
    body: NextLead,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    cl = await campaign_service.get_next_lead(
        db,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        agent_id=body.agent_id,
    )
    if cl is None:
        raise HTTPException(status_code=404, detail="No pending leads for this agent")
    return _campaign_lead_dict(cl)
