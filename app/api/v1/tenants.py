"""Tenant management and setup endpoints.

These endpoints do NOT require X-Tenant-Id — they create/manage tenants and
provide convenience routes for initial user/agent seeding.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenant import Tenant
from app.db.models.user import AgentProfile, AgentStatus, User
from app.dependencies import get_db
from app.schemas import (
    AgentProfileResponse,
    NameStr,
    SlugStr,
    TenantResponse,
    UserResponse,
    UserRoleEnum,
)

router = APIRouter(prefix="/tenants", tags=["tenants"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class TenantCreate(BaseModel):
    name: NameStr
    slug: SlugStr
    config: dict | None = None


class TenantUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    status: str | None = None


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    role: UserRoleEnum


class AgentCreate(BaseModel):
    user_id: UUID
    skills: list[str] | None = None
    max_concurrent: int | None = None
    team: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tenant_response(t: Tenant) -> dict:
    return TenantResponse.model_validate(t).model_dump()


def _user_response(u: User) -> dict:
    return UserResponse.model_validate(u).model_dump()


def _agent_profile_response(ap: AgentProfile, status: AgentStatus | None = None) -> dict:
    d = AgentProfileResponse.model_validate(ap).model_dump()
    if status:
        from app.schemas import AgentStatusResponse
        d["status"] = AgentStatusResponse.model_validate(status).model_dump()
    return d


# ---------------------------------------------------------------------------
# Tenant CRUD
# ---------------------------------------------------------------------------

@router.post("")
async def create_tenant(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
):
    tenant = Tenant(
        name=body.name,
        slug=body.slug,
        config=body.config or {},
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return _tenant_response(tenant)


@router.get("/{tenant_id}")
async def get_tenant(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _tenant_response(tenant)


@router.patch("/{tenant_id}")
async def update_tenant(
    tenant_id: UUID,
    body: TenantUpdate,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    for key, value in updates.items():
        setattr(tenant, key, value)

    await db.commit()
    await db.refresh(tenant)
    return _tenant_response(tenant)


# ---------------------------------------------------------------------------
# User + Agent setup (scoped to a tenant via path param)
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/users")
async def create_user(
    tenant_id: UUID,
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    # Verify tenant exists
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    user = User(
        tenant_id=tenant_id,
        email=body.email,
        name=body.name,
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _user_response(user)


@router.post("/{tenant_id}/agents")
async def create_agent(
    tenant_id: UUID,
    body: AgentCreate,
    db: AsyncSession = Depends(get_db),
):
    # Verify tenant exists
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Verify user exists and belongs to this tenant
    stmt = select(User).where(User.id == body.user_id, User.tenant_id == tenant_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found in this tenant")

    # Check if agent profile already exists
    stmt = select(AgentProfile).where(AgentProfile.user_id == body.user_id)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Agent profile already exists for this user")

    # Create AgentProfile
    agent_profile = AgentProfile(
        tenant_id=tenant_id,
        user_id=body.user_id,
        skills=body.skills or [],
        max_concurrent=body.max_concurrent or 1,
        team=body.team,
    )
    db.add(agent_profile)
    await db.flush()  # get agent_profile.id

    # Create AgentStatus
    agent_status = AgentStatus(
        tenant_id=tenant_id,
        agent_id=agent_profile.id,
    )
    db.add(agent_status)
    await db.commit()
    await db.refresh(agent_profile)
    await db.refresh(agent_status)

    return _agent_profile_response(agent_profile, agent_status)
