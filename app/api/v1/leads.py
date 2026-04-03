"""Lead endpoints — inline SQLAlchemy queries (no service layer)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lead import Lead
from app.dependencies import get_db, get_tenant_id
from app.schemas import LeadResponse, PhoneNumber

router = APIRouter(prefix="/leads", tags=["leads"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class LeadCreate(BaseModel):
    name: str | None = None
    phone: PhoneNumber | None = None
    email: EmailStr | None = None
    whatsapp_number: str | None = None
    metadata: dict | None = None


class LeadUpdate(BaseModel):
    name: str | None = None
    phone: PhoneNumber | None = None
    email: EmailStr | None = None
    whatsapp_number: str | None = None
    metadata: dict | None = None


class LeadImportItem(BaseModel):
    name: str | None = None
    phone: PhoneNumber | None = None
    email: EmailStr | None = None
    whatsapp_number: str | None = None
    metadata: dict | None = None


class LeadImport(BaseModel):
    leads: list[LeadImportItem]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lead_response(lead: Lead) -> dict:
    return LeadResponse.model_validate(lead).model_dump()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("")
async def create_lead(
    body: LeadCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    lead = Lead(
        tenant_id=tenant_id,
        name=body.name,
        phone=body.phone,
        email=body.email,
        whatsapp_number=body.whatsapp_number,
        metadata_=body.metadata or {},
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return _lead_response(lead)


@router.get("")
async def list_leads(
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    stmt = select(Lead).where(
        Lead.tenant_id == tenant_id,
        Lead.is_deleted == False,  # noqa: E712
    )

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                Lead.name.ilike(pattern),
                Lead.phone.ilike(pattern),
                Lead.email.ilike(pattern),
            )
        )

    stmt = stmt.order_by(Lead.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    leads = result.scalars().all()
    return [_lead_response(l) for l in leads]


@router.get("/{lead_id}")
async def get_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    stmt = select(Lead).where(
        Lead.id == lead_id,
        Lead.tenant_id == tenant_id,
        Lead.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _lead_response(lead)


@router.patch("/{lead_id}")
async def update_lead(
    lead_id: UUID,
    body: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    stmt = select(Lead).where(
        Lead.id == lead_id,
        Lead.tenant_id == tenant_id,
        Lead.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    for key, value in updates.items():
        if key == "metadata":
            lead.metadata_ = value
        else:
            setattr(lead, key, value)

    await db.commit()
    await db.refresh(lead)
    return _lead_response(lead)


@router.delete("/{lead_id}")
async def delete_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    stmt = select(Lead).where(
        Lead.id == lead_id,
        Lead.tenant_id == tenant_id,
        Lead.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead.is_deleted = True
    lead.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"detail": "Lead deleted"}


@router.post("/import")
async def import_leads(
    body: LeadImport,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    created: list[dict] = []
    for item in body.leads:
        lead = Lead(
            tenant_id=tenant_id,
            name=item.name,
            phone=item.phone,
            email=item.email,
            whatsapp_number=item.whatsapp_number,
            metadata_=item.metadata or {},
        )
        db.add(lead)
        created.append(lead)

    await db.commit()

    # Refresh all to get server-generated fields
    for lead in created:
        await db.refresh(lead)

    return {"imported": len(created), "leads": [_lead_response(l) for l in created]}
