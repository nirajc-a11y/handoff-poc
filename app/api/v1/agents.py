"""Agent listing, status management, and stats API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, event_bus
from app.dependencies import get_db, get_tenant_id
from app.schemas import AgentResponse, AgentStatusEnum, AgentStatusResponse
from app.services.agent_service import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class UpdateStatusRequest(BaseModel):
    status: AgentStatusEnum


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    """List all agent profiles with their current status."""
    agents = await agent_service.list_agents(db=db, tenant_id=tenant_id)
    return [AgentResponse.model_validate(a) for a in agents]


@router.get("/available", response_model=list[AgentResponse])
async def list_available_agents(
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    """List agents whose current status is 'available'."""
    agents = await agent_service.get_available_agents(db=db, tenant_id=tenant_id)
    return [AgentResponse.model_validate(a) for a in agents]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    """Get a single agent profile with status."""
    agent = await agent_service.get_agent(db=db, tenant_id=tenant_id, agent_id=agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse.model_validate(agent)


@router.patch("/{agent_id}/status", response_model=AgentStatusResponse)
async def update_agent_status(
    agent_id: UUID,
    body: UpdateStatusRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    """Update an agent's availability status."""
    try:
        agent_status = await agent_service.update_status(
            db=db,
            tenant_id=tenant_id,
            agent_id=agent_id,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    result = AgentStatusResponse.model_validate(agent_status)

    await event_bus.publish(Event(
        topic="agent.status_changed",
        tenant_id=tenant_id,
        payload=result.model_dump(),
    ))

    return result


@router.get("/{agent_id}/stats")
async def get_agent_stats(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Get today's conversation stats for an agent."""
    # Verify agent exists
    agent = await agent_service.get_agent(db=db, tenant_id=tenant_id, agent_id=agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    stats = await agent_service.get_agent_stats(
        db=db,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    return {"agent_id": str(agent_id), **stats}
