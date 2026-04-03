"""Handoff, escalation, and queue management API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, event_bus
from app.core.handoff_engine import ConversationNotFoundError, handoff_engine
from app.core.state_machine import StateMachineError, Trigger
from app.dependencies import get_db, get_tenant_id
from app.schemas import ConversationResponse
from app.services.handoff_service import handoff_service

router = APIRouter(prefix="/handoffs", tags=["handoffs"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class EscalateRequest(BaseModel):
    conversation_id: UUID
    reason: str | None = None


class TransferRequest(BaseModel):
    conversation_id: UUID
    target_agent_id: UUID
    warm: bool = False


class IvrSkipRequest(BaseModel):
    conversation_id: UUID


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def _conversation_response(conv) -> dict:
    return ConversationResponse.model_validate(conv).model_dump()


async def _publish_queue_stats(db: AsyncSession, tenant_id: UUID) -> None:
    """Fetch current queue stats and push via event bus."""
    stats = await handoff_service.get_queue_stats(db=db, tenant_id=tenant_id)
    await event_bus.publish(Event(
        topic="queue.stats_updated",
        tenant_id=tenant_id,
        payload=stats,
    ))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/escalate")
async def escalate_to_human(
    body: EscalateRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """AI or system requests escalation to a human agent.

    Delegates to ``handoff_service.escalate_to_human`` which applies the
    ``AI_TRANSFER`` trigger, records the handoff event, and queues the
    conversation for a human.
    """
    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=body.conversation_id,
            trigger=Trigger.AI_TRANSFER,
            metadata={"reason": body.reason} if body.reason else {},
        )
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _publish_queue_stats(db, tenant_id)
    return _conversation_response(conversation)


@router.post("/transfer")
async def transfer_to_agent(
    body: TransferRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Transfer a conversation from one human agent to another (warm or cold)."""
    trigger = Trigger.WARM_TRANSFER if body.warm else Trigger.COLD_TRANSFER
    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=body.conversation_id,
            trigger=trigger,
            metadata={"target_agent_id": str(body.target_agent_id), "warm": body.warm},
        )
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _publish_queue_stats(db, tenant_id)
    return _conversation_response(conversation)


@router.post("/ivr-skip")
async def ivr_skip_to_human(
    body: IvrSkipRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Customer pressed the DTMF key to skip IVR and speak with a human."""
    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=body.conversation_id,
            trigger=Trigger.DTMF_HUMAN,
            metadata={"reason": "Customer requested human via IVR"},
        )
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _publish_queue_stats(db, tenant_id)
    return _conversation_response(conversation)


@router.get("/queue")
async def get_queue(
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> list[dict]:
    """List conversations currently queued for a human agent, ordered by priority then wait time."""
    conversations = await handoff_service.get_queue(
        db=db,
        tenant_id=tenant_id,
    )
    return [_conversation_response(c) for c in conversations]


@router.get("/queue/stats")
async def get_queue_stats(
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Return queue depth, average wait time, and breakdown by required skill."""
    return await handoff_service.get_queue_stats(
        db=db,
        tenant_id=tenant_id,
    )
