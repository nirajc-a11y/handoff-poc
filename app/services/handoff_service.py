"""Service layer for conversation handoff / escalation operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.state_machine import ConversationState, Trigger, transition
from app.db.models.conversation import Conversation
from app.db.models.handoff_event import HandoffEvent

logger = logging.getLogger(__name__)


class HandoffService:
    """Orchestrates escalation, transfer, and queue management for conversations."""

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    async def _process_trigger(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        conversation_id: UUID,
        trigger: Trigger,
        reason: str | None = None,
        target_handler_type: str | None = None,
        target_handler_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> Conversation:
        """Apply a state-machine trigger to a conversation and record a HandoffEvent."""
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise ValueError(
                f"Conversation not found (id={conversation_id}, tenant_id={tenant_id})"
            )

        current_state = ConversationState(conversation.state)
        new_state, event_type = transition(current_state, trigger)

        # Capture previous handler info before updating
        from_handler_type = conversation.current_handler_type
        from_handler_id = conversation.current_handler_id

        # Update conversation state
        conversation.state = new_state.value

        if target_handler_type is not None:
            conversation.current_handler_type = target_handler_type
        if target_handler_id is not None:
            conversation.current_handler_id = target_handler_id

        # Track queue entry time
        if new_state == ConversationState.QUEUED_FOR_HUMAN:
            conversation.queue_entered_at = datetime.now(timezone.utc)
        elif current_state == ConversationState.QUEUED_FOR_HUMAN:
            conversation.queue_entered_at = None

        if reason:
            conversation.ai_escalation_reason = reason

        # Record the handoff event
        event = HandoffEvent(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            event_type=event_type,
            from_handler_type=from_handler_type,
            from_handler_id=from_handler_id,
            to_handler_type=target_handler_type or conversation.current_handler_type,
            to_handler_id=target_handler_id,
            from_state=current_state.value,
            to_state=new_state.value,
            reason=reason,
            context_snapshot=conversation.context,
            metadata_=metadata or {},
        )
        db.add(event)
        await db.commit()

        logger.info(
            "Handoff: conversation %s transitioned %s -> %s (trigger=%s, event=%s) tenant %s",
            conversation_id,
            current_state.value,
            new_state.value,
            trigger.value,
            event_type,
            tenant_id,
        )
        return conversation

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def escalate_to_human(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        conversation_id: UUID,
        reason: str | None = None,
    ) -> Conversation:
        """AI decides to transfer to a human agent."""
        return await self._process_trigger(
            db,
            tenant_id,
            conversation_id,
            trigger=Trigger.AI_TRANSFER,
            reason=reason,
            target_handler_type="system",
            target_handler_id=None,
        )

    async def transfer_to_agent(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        conversation_id: UUID,
        target_agent_id: UUID,
        warm: bool = False,
    ) -> Conversation:
        """Transfer from one human agent to another (warm or cold)."""
        trigger = Trigger.WARM_TRANSFER if warm else Trigger.COLD_TRANSFER
        return await self._process_trigger(
            db,
            tenant_id,
            conversation_id,
            trigger=trigger,
            target_handler_type="human",
            target_handler_id=target_agent_id,
            metadata={"warm": warm, "target_agent_id": str(target_agent_id)},
        )

    async def ivr_skip_to_human(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        conversation_id: UUID,
    ) -> Conversation:
        """Customer pressed the DTMF key to skip IVR and speak with a human."""
        return await self._process_trigger(
            db,
            tenant_id,
            conversation_id,
            trigger=Trigger.DTMF_HUMAN,
            reason="Customer requested human via IVR",
            target_handler_type="system",
            target_handler_id=None,
        )

    async def get_queue(
        self,
        db: AsyncSession,
        tenant_id: UUID,
    ) -> list[Conversation]:
        """Return conversations waiting for a human agent, ordered by priority then wait time."""
        stmt = (
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.state == ConversationState.QUEUED_FOR_HUMAN.value,
            )
            .order_by(
                Conversation.queue_priority.desc(),
                Conversation.queue_entered_at.asc(),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_queue_stats(
        self,
        db: AsyncSession,
        tenant_id: UUID,
    ) -> dict:
        """Return queue depth, average wait time, and breakdown by required skill."""
        now = datetime.now(timezone.utc)

        # Queue depth
        depth_stmt = (
            select(func.count(Conversation.id))
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.state == ConversationState.QUEUED_FOR_HUMAN.value,
            )
        )
        depth_result = await db.execute(depth_stmt)
        queue_depth = depth_result.scalar() or 0

        # Average wait in seconds
        avg_wait_stmt = (
            select(func.avg(func.extract("epoch", now - Conversation.queue_entered_at)))
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.state == ConversationState.QUEUED_FOR_HUMAN.value,
                Conversation.queue_entered_at.isnot(None),
            )
        )
        avg_result = await db.execute(avg_wait_stmt)
        avg_wait_seconds = round(float(avg_result.scalar() or 0), 1)

        # Breakdown by required_skills (simplified: count per distinct skills JSON)
        skill_stmt = (
            select(Conversation.required_skills, func.count(Conversation.id))
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.state == ConversationState.QUEUED_FOR_HUMAN.value,
            )
            .group_by(Conversation.required_skills)
        )
        skill_result = await db.execute(skill_stmt)
        by_skill: dict = {}
        for skills, count in skill_result.all():
            key = ",".join(sorted(skills)) if skills else "none"
            by_skill[key] = count

        return {
            "queue_depth": queue_depth,
            "avg_wait_seconds": avg_wait_seconds,
            "by_skill": by_skill,
        }


handoff_service = HandoffService()
