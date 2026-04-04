"""Voice call lifecycle API endpoints."""

from __future__ import annotations

from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.handoff_engine import ConversationNotFoundError, handoff_engine
from app.core.ivr_engine import ivr_engine
from app.core.state_machine import ConversationState, StateMachineError, Trigger
from app.db.models.lead import Lead
from app.db.models.user import AgentProfile
from app.dependencies import get_current_user_id, get_db, get_tenant_id
from app.schemas import ConversationResponse, PhoneNumber
from app.services.call_service import call_service
from app.services.campaign_service import campaign_service
from app.services.conversation_service import conversation_service

router = APIRouter(prefix="/calls", tags=["calls"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class OutboundCallRequest(BaseModel):
    to_number: PhoneNumber
    customer_name: str | None = None
    lead_id: UUID | None = None
    campaign_lead_id: UUID | None = None


class CampaignCallRequest(BaseModel):
    campaign_id: UUID


class InboundWebhookRequest(BaseModel):
    from_number: str
    to_number: str
    provider_call_id: str
    customer_name: str | None = None


class TransferRequest(BaseModel):
    target_agent_id: UUID
    warm: bool = False


class DtmfRequest(BaseModel):
    digit: Annotated[str, Field(pattern=r"^[0-9*#]$")]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _conversation_response(conv) -> dict:
    return ConversationResponse.model_validate(conv).model_dump()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/outbound")
async def initiate_outbound_call(
    body: OutboundCallRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user_id: UUID = Depends(get_current_user_id),
) -> dict:
    """Place an outbound voice call and transition the conversation to RINGING."""
    conversation = await call_service.initiate_outbound_call(
        db=db,
        tenant_id=tenant_id,
        agent_id=user_id,
        to_number=body.to_number,
        customer_name=body.customer_name,
        lead_id=body.lead_id,
        campaign_lead_id=body.campaign_lead_id,
    )

    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation.id,
            trigger=Trigger.DIAL,
        )
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _conversation_response(conversation)


@router.post("/outbound/campaign")
async def initiate_campaign_call(
    body: CampaignCallRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user_id: UUID = Depends(get_current_user_id),
) -> dict:
    """Get the next lead from a campaign and place an outbound call."""
    # Resolve agent_profile.id from user_id (campaign_leads are assigned to agent profiles, not users)
    agent_stmt = select(AgentProfile.id).where(
        AgentProfile.user_id == user_id,
        AgentProfile.tenant_id == tenant_id,
    )
    agent_result = await db.execute(agent_stmt)
    agent_profile_id = agent_result.scalar_one_or_none()

    campaign_lead = await campaign_service.get_next_lead(
        db=db,
        tenant_id=tenant_id,
        campaign_id=body.campaign_id,
        agent_id=agent_profile_id or user_id,
    )
    if campaign_lead is None:
        raise HTTPException(status_code=404, detail="No pending leads available in this campaign")

    # Resolve the lead's phone number
    lead_stmt = select(Lead).where(Lead.id == campaign_lead.lead_id)
    lead_result = await db.execute(lead_stmt)
    lead = lead_result.scalar_one_or_none()
    if lead is None or not lead.phone:
        raise HTTPException(status_code=404, detail="Lead or lead phone number not found")

    conversation = await call_service.initiate_outbound_call(
        db=db,
        tenant_id=tenant_id,
        agent_id=user_id,
        to_number=lead.phone,
        customer_name=lead.name,
        lead_id=campaign_lead.lead_id,
        campaign_lead_id=campaign_lead.id,
    )

    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation.id,
            trigger=Trigger.DIAL,
        )
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _conversation_response(conversation)


@router.post("/inbound/webhook")
async def inbound_webhook(
    body: InboundWebhookRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Handle an inbound call notification from the telephony provider."""
    conversation = await call_service.handle_inbound_call(
        db=db,
        tenant_id=tenant_id,
        from_number=body.from_number,
        to_number=body.to_number,
        provider_call_id=body.provider_call_id,
        customer_name=body.customer_name,
    )

    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation.id,
            trigger=Trigger.RING,
        )
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _conversation_response(conversation)


@router.post("/{conversation_id}/answer")
async def answer_call(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Simulate answering an inbound call — transitions from RINGING to IVR."""
    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=Trigger.ANSWER,
        )
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="Call not found")
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _conversation_response(conversation)


@router.get("/{conversation_id}")
async def get_call(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Retrieve details for a voice call / conversation."""
    conversation = await call_service.get_call(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Call not found")

    return _conversation_response(conversation)


@router.post("/{conversation_id}/hold")
async def hold_call(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Place a call on hold."""
    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=Trigger.AGENT_HOLD,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _conversation_response(conversation)


@router.post("/{conversation_id}/unhold")
async def unhold_call(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Resume a call from hold."""
    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=Trigger.AGENT_UNHOLD,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _conversation_response(conversation)


@router.post("/{conversation_id}/transfer")
async def transfer_call(
    conversation_id: UUID,
    body: TransferRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Initiate a warm or cold transfer to another agent."""
    trigger = Trigger.WARM_TRANSFER if body.warm else Trigger.COLD_TRANSFER
    metadata = {
        "target_agent_id": str(body.target_agent_id),
        "transfer_type": "warm" if body.warm else "cold",
    }

    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=trigger,
            metadata=metadata,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _conversation_response(conversation)


@router.post("/{conversation_id}/end")
async def end_call(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Agent ends the call — moves through wrap-up to ended."""
    try:
        conversation = await call_service.get_call(db=db, tenant_id=tenant_id, conversation_id=conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Call not found")
        # If already ENDED, nothing to do
        if conversation.state == ConversationState.ENDED:
            return _conversation_response(conversation)
        # If already in WRAP_UP (e.g. AI resolved / customer disconnected), skip AGENT_END
        if conversation.state != ConversationState.WRAP_UP:
            conversation = await handoff_engine.process_trigger(
                db=db,
                conversation_id=conversation_id,
                trigger=Trigger.AGENT_END,
            )
        # Complete wrap-up so the call is fully ended
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=Trigger.DISPOSITION_SUBMITTED,
            metadata={"disposition": "ended_by_agent"},
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _conversation_response(conversation)


@router.post("/{conversation_id}/force-end")
async def force_end_call(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Force-end a stuck call (e.g. customer hung up during IVR/AI)."""
    try:
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=Trigger.CUSTOMER_DISCONNECT,
        )
        # Auto-complete wrap-up so the call is fully ended
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=Trigger.DISPOSITION_SUBMITTED,
            metadata={"disposition": "customer_disconnected"},
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _conversation_response(conversation)


@router.post("/{conversation_id}/dtmf")
async def dtmf_input(
    conversation_id: UUID,
    body: DtmfRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
) -> dict:
    """Handle a DTMF tone during IVR.

    Looks up the IVR menu configuration from the conversation context and
    delegates to ``ivr_engine.process_dtmf`` for proper routing.  Falls back
    to the legacy heuristic (digit ``"0"`` → human, else → AI) when no IVR
    menu is configured.
    """
    try:
        # Load the conversation to check for an active IVR menu
        conv = await conversation_service.get_conversation(
            db, tenant_id, conversation_id,
        )
        if conv is None:
            raise ConversationNotFoundError(conversation_id)

        ivr_menu_id = (conv.context or {}).get("ivr_menu_id")

        if ivr_menu_id is not None:
            # ---- IVR-menu-driven routing ----
            action = await ivr_engine.process_dtmf(
                db, tenant_id, ivr_menu_id, body.digit,
            )

            if action.action_type == "ai_handoff":
                conversation = await handoff_engine.process_trigger(
                    db=db,
                    conversation_id=conversation_id,
                    trigger=Trigger.DTMF_AI,
                    metadata={
                        "digit": body.digit,
                        "target_config": action.target_config,
                    },
                )
                return _conversation_response(conversation)

            if action.action_type == "human_queue":
                conversation = await handoff_engine.process_trigger(
                    db=db,
                    conversation_id=conversation_id,
                    trigger=Trigger.DTMF_HUMAN,
                    metadata={
                        "digit": body.digit,
                        "target_config": action.target_config,
                    },
                )
                return _conversation_response(conversation)

            if action.action_type == "submenu":
                # Navigate to the submenu — update context, return new prompt
                conv.context = {
                    **(conv.context or {}),
                    "ivr_menu_id": str(action.target_id),
                }
                db.add(conv)
                await db.commit()
                await db.refresh(conv)

                prompt, _ = await ivr_engine.get_menu_prompt(
                    db, tenant_id, action.target_id,
                )
                return {
                    "status": "submenu",
                    "prompt": prompt,
                    "conversation_id": str(conversation_id),
                }

            if action.action_type == "play_message":
                return {
                    "status": "play_message",
                    "message": action.message,
                    "conversation_id": str(conversation_id),
                }

            if action.action_type == "hangup":
                conversation = await handoff_engine.process_trigger(
                    db=db,
                    conversation_id=conversation_id,
                    trigger=Trigger.CUSTOMER_DISCONNECT,
                    metadata={"digit": body.digit},
                )
                return _conversation_response(conversation)

        # ---- Legacy fallback: no IVR menu configured ----
        trigger = Trigger.DTMF_HUMAN if body.digit == "0" else Trigger.DTMF_AI
        conversation = await handoff_engine.process_trigger(
            db=db,
            conversation_id=conversation_id,
            trigger=trigger,
            metadata={"digit": body.digit},
        )

    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _conversation_response(conversation)
