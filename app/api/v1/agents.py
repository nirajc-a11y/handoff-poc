"""Agent listing, status management, and stats API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, event_bus
from app.dependencies import get_db, get_tenant_id
from app.services.agent_service import agent_service

router = APIRouter(prefix="/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class UpdateStatusRequest(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _agent_to_dict(agent) -> dict:
    result: dict = {
        "id": str(agent.id),
        "tenant_id": str(agent.tenant_id),
        "user_id": str(agent.user_id),
        "skills": agent.skills,
        "max_concurrent": agent.max_concurrent,
        "team": agent.team,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
    }
    if agent.status is not None:
        result["status"] = {
            "status": agent.status.status,
            "current_conversations": agent.status.current_conversations,
            "last_status_change": (
                agent.status.last_status_change.isoformat()
                if agent.status.last_status_change
                else None
            ),
        }
    else:
        result["status"] = None
    return result


def _agent_status_to_dict(agent_status) -> dict:
    return {
        "agent_id": str(agent_status.agent_id),
        "tenant_id": str(agent_status.tenant_id),
        "status": agent_status.status,
        "current_conversations": agent_status.current_conversations,
        "last_status_change": (
            agent_status.last_status_change.isoformat()
            if agent_status.last_status_change
            else None
        ),
        "updated_at": (
            agent_status.updated_at.isoformat() if agent_status.updated_at else None
        ),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_agents(
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> list[dict]:
    """List all agent profiles with their current status."""
    agents = await agent_service.list_agents(db=db, tenant_id=tenant_id)
    return [_agent_to_dict(a) for a in agents]


@router.get("/available")
async def list_available_agents(
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> list[dict]:
    """List agents whose current status is 'available'."""
    agents = await agent_service.get_available_agents(db=db, tenant_id=tenant_id)
    return [_agent_to_dict(a) for a in agents]


@router.get("/{agent_id}")
async def get_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Get a single agent profile with status."""
    agent = await agent_service.get_agent(db=db, tenant_id=tenant_id, agent_id=agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_to_dict(agent)


@router.patch("/{agent_id}/status")
async def update_agent_status(
    agent_id: UUID,
    body: UpdateStatusRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
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

    result = _agent_status_to_dict(agent_status)

    await event_bus.publish(Event(
        topic="agent.status_changed",
        tenant_id=tenant_id,
        payload=result,
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
