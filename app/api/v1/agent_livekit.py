"""LiveKit token endpoint for human agents.

Generates LiveKit room access tokens so human agents can join
a call's LiveKit room via the browser client. The bridge handles
all audio conversion between LiveKit and Plivo.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.conversation import Conversation
from app.dependencies import get_db, get_current_user_id, get_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent-livekit"])


class LiveKitTokenResponse(BaseModel):
    token: str
    url: str
    room: str


@router.post("/livekit-token/{conv_id}", response_model=LiveKitTokenResponse)
async def get_agent_livekit_token(
    conv_id: str,
    agent_id: UUID = Depends(get_current_user_id),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> LiveKitTokenResponse:
    """Generate a LiveKit room token for a human agent to join a call.

    The agent must be the currently assigned handler for the conversation.
    Returns a JWT token, the LiveKit server URL, and the room name.
    """
    if not settings.use_livekit_agent or not settings.livekit_url:
        raise HTTPException(status_code=400, detail="LiveKit agent mode is not enabled")

    # Verify the conversation exists and the agent is assigned
    conv_uuid = UUID(conv_id)
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_uuid,
            Conversation.tenant_id == tenant_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conversation.current_handler_id != agent_id:
        raise HTTPException(
            status_code=403,
            detail="Agent is not assigned to this conversation",
        )

    room_name = f"room-{conv_id}"

    from livekit import api as lk_api

    token = lk_api.AccessToken(
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    token.with_identity(f"agent-{agent_id}")
    token.with_name("Human Agent")
    token.with_grants(
        lk_api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
    )
    jwt_token = token.to_jwt()

    logger.info(
        "Generated LiveKit token for agent %s to join room %s (conv=%s)",
        agent_id, room_name, conv_id,
    )

    return LiveKitTokenResponse(
        token=jwt_token,
        url=settings.livekit_url,
        room=room_name,
    )
