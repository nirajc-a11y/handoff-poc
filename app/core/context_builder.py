"""Builds rich handoff context payloads for conversation transfers."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.conversation import Conversation
from app.db.models.handoff_event import HandoffEvent
from app.db.models.message import Message

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Assembles a context dictionary that accompanies a conversation when it
    is handed off between IVR, AI, and human handlers."""

    async def build_handoff_context(
        self,
        db: AsyncSession,
        conversation_id: UUID,
        tenant_id: UUID,
    ) -> dict:
        """Load conversation data and compile a handoff context payload.

        The returned dict is intended to be stored in ``HandoffEvent.context_snapshot``
        or sent to the receiving agent's UI.
        """
        # -- Load conversation with relationships --
        conv_stmt = (
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
            .options(
                selectinload(Conversation.messages),
                selectinload(Conversation.handoff_events),
            )
        )
        result = await db.execute(conv_stmt)
        conversation = result.scalar_one_or_none()

        if conversation is None:
            raise ValueError(
                f"Conversation not found (id={conversation_id}, tenant_id={tenant_id})"
            )

        # -- Derive summary from the last N messages --
        recent_messages = conversation.messages[-5:] if conversation.messages else []
        conversation_summary = self._summarize_messages(recent_messages)

        # -- Extract IVR (DTMF) selections --
        ivr_selections = self._extract_ivr_selections(conversation.messages)

        # -- Count AI turns and find last confidence score --
        ai_turns, ai_confidence = self._extract_ai_metadata(conversation.messages, conversation)

        # -- Build handler change history from handoff events --
        previous_handlers = self._extract_handler_history(conversation.handoff_events)

        # -- Determine escalation reason --
        escalation_reason = self._extract_escalation_reason(conversation)

        return {
            "customer_identifier": conversation.customer_identifier,
            "customer_name": conversation.customer_name,
            "channel": conversation.channel,
            "direction": conversation.direction,
            "conversation_summary": conversation_summary,
            "ivr_selections": ivr_selections,
            "ai_turns": ai_turns,
            "ai_confidence": ai_confidence,
            "escalation_reason": escalation_reason,
            "previous_handlers": previous_handlers,
            "accumulated_context": conversation.context or {},
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_messages(messages: list[Message]) -> list[dict]:
        """Return a compact representation of the last few messages."""
        summary: list[dict] = []
        for msg in messages:
            summary.append(
                {
                    "sender_type": msg.sender_type,
                    "content_type": msg.content_type,
                    "content": (msg.content[:200] + "...") if msg.content and len(msg.content) > 200 else msg.content,
                    "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                }
            )
        return summary

    @staticmethod
    def _extract_ivr_selections(messages: list[Message]) -> list[dict]:
        """Pull DTMF digit messages from the conversation timeline."""
        selections: list[dict] = []
        for msg in messages:
            if msg.content_type == "dtmf":
                selections.append(
                    {
                        "digit": msg.content,
                        "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                        "metadata": msg.metadata_ or {},
                    }
                )
        return selections

    @staticmethod
    def _extract_ai_metadata(
        messages: list[Message],
        conversation: Conversation,
    ) -> tuple[int, float | None]:
        """Count AI-sent messages and resolve the latest confidence score."""
        ai_turns = sum(1 for m in messages if m.sender_type == "ai")

        # Prefer the conversation-level score; fall back to the last AI
        # message's metadata if available.
        ai_confidence: float | None = conversation.ai_confidence_score
        if ai_confidence is None:
            for msg in reversed(messages):
                if msg.sender_type == "ai" and msg.metadata_:
                    ai_confidence = msg.metadata_.get("confidence")
                    if ai_confidence is not None:
                        break

        return ai_turns, ai_confidence

    @staticmethod
    def _extract_handler_history(events: list[HandoffEvent]) -> list[dict]:
        """Compile a chronological list of handler transitions."""
        handlers: list[dict] = []
        for event in events:
            handlers.append(
                {
                    "event_type": event.event_type,
                    "from_handler_type": event.from_handler_type,
                    "from_handler_id": str(event.from_handler_id) if event.from_handler_id else None,
                    "to_handler_type": event.to_handler_type,
                    "to_handler_id": str(event.to_handler_id) if event.to_handler_id else None,
                    "from_state": event.from_state,
                    "to_state": event.to_state,
                    "reason": event.reason,
                    "timestamp": event.created_at.isoformat() if event.created_at else None,
                }
            )
        return handlers

    @staticmethod
    def _extract_escalation_reason(conversation: Conversation) -> str | None:
        """Return the escalation reason from the conversation or its latest handoff event."""
        if conversation.ai_escalation_reason:
            return conversation.ai_escalation_reason

        # Fall back to the most recent handoff event's reason
        if conversation.handoff_events:
            for event in reversed(conversation.handoff_events):
                if event.reason:
                    return event.reason

        return None


# Module-level singleton
context_builder = ContextBuilder()
