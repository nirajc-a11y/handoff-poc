"""Handoff engine — the central orchestrator for all conversation state
transitions and handler handoffs.

Every state change in a conversation flows through ``HandoffEngine.process_trigger``.
It validates the transition against the state machine, executes the appropriate
side effects (routing, provider calls, context building), persists the change,
and publishes events for downstream consumers.

When ``settings.use_livekit_agent`` is True, handoff side-effects send LiveKit
data channel messages instead of redirecting Plivo calls. The Plivo-LiveKit
bridge stays connected throughout the entire call lifecycle.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.ai_engine import AIEngine, ai_engine
from app.core.context_builder import ContextBuilder, context_builder
from app.core.events import Event, EventBus, event_bus
from app.core.ivr_engine import IVREngine, ivr_engine
from app.core.routing_engine import RoutingEngine, routing_engine
from app.core.state_machine import (
    ConversationState,
    StateMachineError,
    Trigger,
    transition,
)
from app.db.models.conversation import Conversation
from app.db.models.handoff_event import HandoffEvent
from app.providers.registry import ProviderRegistry, provider_registry

logger = logging.getLogger(__name__)


class ConversationNotFoundError(Exception):
    """Raised when a conversation cannot be found by ID."""

    def __init__(self, conversation_id: UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation not found: {conversation_id}")


class ConversationLockedError(Exception):
    """Raised when a conversation row is already locked by another transaction."""

    def __init__(self, conversation_id: UUID) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation is locked by another transaction: {conversation_id}")


class HandoffEngine:
    """Orchestrates every conversation state transition and handler handoff.

    All mutations to ``Conversation.state`` must go through
    :meth:`process_trigger`.  The method acquires a row-level lock
    (``SELECT FOR UPDATE``) to guarantee serialisable transitions even under
    concurrent requests.
    """

    def __init__(
        self,
        provider_registry: ProviderRegistry,
        event_bus: EventBus,
        routing_engine: RoutingEngine,
        ai_engine: AIEngine,
        ivr_engine: IVREngine,
        context_builder: ContextBuilder,
    ) -> None:
        self._provider_registry = provider_registry
        self._event_bus = event_bus
        self._routing_engine = routing_engine
        self._ai_engine = ai_engine
        self._ivr_engine = ivr_engine
        self._context_builder = context_builder

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def process_trigger(
        self,
        db: AsyncSession,
        conversation_id: UUID,
        trigger: Trigger,
        metadata: dict | None = None,
    ) -> Conversation:
        """Execute a state transition.  This is **the** single entry point for
        all handoffs, hold/unhold actions, transfers, and call lifecycle events.

        Raises:
            ConversationNotFoundError: If the conversation does not exist.
            StateMachineError: If the trigger is invalid for the current state
                (callers should map this to HTTP 400).
        """
        metadata = metadata or {}

        # 1. Load conversation with row-level lock
        conversation = await self._load_conversation(db, conversation_id)

        # 2. Resolve current state as the enum
        current_state = ConversationState(conversation.state)

        # 3. Validate transition (raises StateMachineError on invalid)
        new_state, event_type = transition(current_state, trigger)

        # 4. Capture previous handler info before side effects mutate it
        prev_handler_type = conversation.current_handler_type
        prev_handler_id = conversation.current_handler_id

        # 5. Execute side effects for the target state
        await self._execute_side_effects(
            db, conversation, trigger, current_state, new_state, metadata,
        )

        # 6. Update conversation state — but only if a side-effect handler
        #    hasn't already advanced it further (e.g. queue -> immediate assign)
        if conversation.state == current_state.value:
            conversation.state = new_state.value
            # Sub-state is managed by side-effect handlers; clear it when
            # transitioning to a state that doesn't explicitly set one.
            if new_state not in (
                ConversationState.ON_HOLD,
                ConversationState.TRANSFERRED,
                ConversationState.WRAP_UP,
            ):
                conversation.sub_state = None

        # 7. Persist handoff event record
        handoff_event = await self._create_handoff_event(
            db=db,
            conversation=conversation,
            event_type=event_type,
            from_handler_type=prev_handler_type,
            from_handler_id=prev_handler_id,
            to_handler_type=conversation.current_handler_type,
            to_handler_id=conversation.current_handler_id,
            from_state=current_state.value,
            to_state=new_state.value,
            reason=metadata.get("reason"),
            metadata=metadata,
        )

        # 8. Commit all changes
        await db.commit()
        await db.refresh(conversation)

        # 9. Publish event (fire-and-forget after commit so subscribers see
        #    committed data)
        await self._publish_event(
            conversation=conversation,
            event_type=event_type,
            from_state=current_state.value,
            to_state=new_state.value,
            metadata=metadata,
        )

        logger.info(
            "Conversation %s transitioned: %s -> %s (trigger=%s, event=%s)",
            conversation_id,
            current_state.value,
            new_state.value,
            trigger.value,
            event_type,
        )

        # 10. Return updated conversation
        return conversation

    # ------------------------------------------------------------------
    # Side-effect dispatcher
    # ------------------------------------------------------------------

    async def _execute_side_effects(
        self,
        db: AsyncSession,
        conversation: Conversation,
        trigger: Trigger,
        old_state: ConversationState,
        new_state: ConversationState,
        metadata: dict,
    ) -> None:
        """Route to the correct handler based on the target state and trigger."""

        if new_state is ConversationState.IVR:
            await self._handle_ivr_entry(db, conversation, metadata)

        elif new_state is ConversationState.AI_HANDLING:
            await self._handle_ai_entry(db, conversation, metadata)

        elif new_state is ConversationState.QUEUED_FOR_HUMAN:
            await self._handle_queue_for_human(db, conversation, metadata)

        elif new_state is ConversationState.HUMAN_HANDLING:
            if trigger is Trigger.AGENT_ASSIGNED:
                await self._handle_agent_assignment(db, conversation, metadata)
            elif trigger is Trigger.TRANSFER_ACCEPTED:
                await self._handle_transfer_complete(db, conversation, metadata)
            elif trigger is Trigger.AGENT_UNHOLD:
                await self._handle_unhold(db, conversation, metadata)
            elif trigger is Trigger.TRANSFER_FAILED:
                # Transfer failed — revert to the current handler; nothing to
                # change beyond the state (already set by the caller).
                conversation.sub_state = None

        elif new_state is ConversationState.ON_HOLD:
            await self._handle_hold(db, conversation, metadata)

        elif new_state is ConversationState.TRANSFERRED:
            await self._handle_transfer(db, conversation, new_state, metadata)

        elif new_state is ConversationState.WRAP_UP:
            await self._handle_wrap_up(db, conversation, metadata)

        elif new_state is ConversationState.ENDED:
            await self._handle_ended(db, conversation, metadata)

        elif new_state is ConversationState.FAILED:
            await self._handle_failed(db, conversation, metadata)

        # RINGING and INITIATED are pure state-change transitions with no side
        # effects beyond the state update itself.

    # ------------------------------------------------------------------
    # Side-effect handlers
    # ------------------------------------------------------------------

    async def _handle_ivr_entry(
        self,
        db: AsyncSession,
        conversation: Conversation,
        metadata: dict,
    ) -> None:
        """Set handler to IVR and fetch the root menu prompt."""
        conversation.current_handler_type = "ivr"
        conversation.current_handler_id = None

        try:
            prompt, menu_id = await self._ivr_engine.get_menu_prompt(
                db,
                tenant_id=conversation.tenant_id,
                menu_id=metadata.get("menu_id"),
            )
            # Stash the prompt and current menu in context so the API layer
            # can relay it to the caller.
            conversation.context = {
                **(conversation.context or {}),
                "ivr_prompt": prompt,
                "ivr_menu_id": str(menu_id),
            }
        except ValueError:
            logger.warning(
                "No IVR menu found for tenant %s — using default prompt",
                conversation.tenant_id,
            )
            conversation.context = {
                **(conversation.context or {}),
                "ivr_prompt": "Welcome. Please hold while we connect you.",
            }

    async def _handle_ai_entry(
        self,
        db: AsyncSession,
        conversation: Conversation,
        metadata: dict,
    ) -> None:
        """Transition the conversation to AI handling."""
        conversation.current_handler_type = "ai"
        conversation.current_handler_id = None
        conversation.answered_at = conversation.answered_at or datetime.now(timezone.utc)

    async def _handle_queue_for_human(
        self,
        db: AsyncSession,
        conversation: Conversation,
        metadata: dict,
    ) -> None:
        """Queue the conversation for a human agent.

        Builds a rich handoff context, records queue timing, and attempts an
        immediate agent match.  If an agent is available the engine recursively
        triggers ``AGENT_ASSIGNED`` so that the conversation moves straight to
        ``HUMAN_HANDLING`` within the same transaction.
        """
        # Build context payload for the receiving agent
        try:
            context_payload = await self._context_builder.build_handoff_context(
                db,
                conversation_id=conversation.id,
                tenant_id=conversation.tenant_id,
            )
            conversation.context = {
                **(conversation.context or {}),
                "handoff_context": context_payload,
            }
        except ValueError:
            logger.warning(
                "Could not build handoff context for conversation %s",
                conversation.id,
            )

        # Mark queue entry
        conversation.queue_entered_at = datetime.now(timezone.utc)
        conversation.current_handler_type = "system"
        conversation.current_handler_id = None

        # Carry over skill requirements from metadata
        required_skills: list[str] | None = metadata.get("required_skills")
        if required_skills:
            conversation.required_skills = required_skills

        # Set priority if provided
        if "queue_priority" in metadata:
            conversation.queue_priority = int(metadata["queue_priority"])

        # Flush so routing queries can see the updated conversation
        await db.flush()

        # Signal the AI agent to disconnect (LiveKit path)
        await self._send_room_data(conversation.id, {
            "type": "handoff",
            "reason": metadata.get("reason", "escalation"),
            "conversation_id": str(conversation.id),
        })

        # Attempt immediate agent assignment
        agent_id = await self._routing_engine.find_available_agent(
            db,
            tenant_id=conversation.tenant_id,
            required_skills=required_skills,
        )

        if agent_id is not None:
            # Recursive trigger — stays inside the same transaction/lock.
            # We must update the state manually before re-entering
            # ``process_trigger`` would try to lock the row again (already
            # locked), so we handle the assignment inline instead.
            try:
                await self._handle_agent_assignment(
                    db, conversation, {**metadata, "agent_id": str(agent_id)},
                )
            except Exception:
                logger.exception(
                    "Failed to assign agent inline for conversation %s "
                    "(tenant=%s) — leaving in QUEUED_FOR_HUMAN",
                    conversation.id,
                    conversation.tenant_id,
                )
                return
            # Advance the state directly since we're bypassing the outer
            # process_trigger flow.
            conversation.state = ConversationState.HUMAN_HANDLING.value
            conversation.sub_state = None

            # Record the additional handoff event for the immediate assignment
            await self._create_handoff_event(
                db=db,
                conversation=conversation,
                event_type="handler_change",
                from_handler_type="system",
                from_handler_id=None,
                to_handler_type="human",
                to_handler_id=agent_id,
                from_state=ConversationState.QUEUED_FOR_HUMAN.value,
                to_state=ConversationState.HUMAN_HANDLING.value,
                reason="immediate_assignment",
                metadata=metadata,
            )

    async def _handle_agent_assignment(
        self,
        db: AsyncSession,
        conversation: Conversation,
        metadata: dict,
    ) -> None:
        """Assign a specific agent to the conversation."""
        agent_id_raw = metadata.get("agent_id")
        if agent_id_raw is None:
            raise ValueError(
                "metadata must include 'agent_id' for AGENT_ASSIGNED trigger"
            )

        agent_id = UUID(str(agent_id_raw))

        conversation.current_handler_type = "human"
        conversation.current_handler_id = agent_id

        # Record first-answer time
        if conversation.answered_at is None:
            conversation.answered_at = datetime.now(timezone.utc)

        # Update routing engine counters
        await self._routing_engine.assign_agent(
            db, agent_id=agent_id, tenant_id=conversation.tenant_id,
        )

        # Notify the LiveKit room that a human agent has been assigned
        await self._send_room_data(conversation.id, {
            "type": "agent_assigned",
            "agent_id": str(agent_id),
            "conversation_id": str(conversation.id),
        })

    async def _handle_transfer(
        self,
        db: AsyncSession,
        conversation: Conversation,
        new_state: ConversationState,
        metadata: dict,
    ) -> None:
        """Initiate a warm or cold transfer.

        - **Warm transfer**: the originating agent stays connected while the
          target agent is contacted.  ``sub_state`` is set to
          ``transfer_pending``.
        - **Cold transfer**: the originating agent disconnects immediately and
          the current handler is cleared.
        """
        transfer_type = metadata.get("transfer_type", "cold")
        target_agent_id = metadata.get("target_agent_id")

        # Persist the target so _handle_transfer_complete can retrieve it.
        conversation.context = {
            **(conversation.context or {}),
            "transfer_target_agent_id": str(target_agent_id) if target_agent_id else None,
            "transfer_type": transfer_type,
            "transfer_initiated_by": str(conversation.current_handler_id)
            if conversation.current_handler_id
            else None,
        }

        if transfer_type == "warm":
            conversation.sub_state = "transfer_pending"
            # Warm: originating agent stays connected — don't clear handler.
            # Signal room so target agent can join alongside originating agent
            await self._send_room_data(conversation.id, {
                "type": "transfer_pending",
                "transfer_type": "warm",
                "target_agent_id": str(target_agent_id) if target_agent_id else None,
            })
        else:
            # Cold: originating agent disconnects immediately.
            prev_agent_id = conversation.current_handler_id
            conversation.sub_state = "transfer_pending"
            conversation.current_handler_type = "system"
            conversation.current_handler_id = None

            # Signal the current agent to disconnect from the room
            await self._send_room_data(conversation.id, {
                "type": "transfer_disconnect",
                "transfer_type": "cold",
                "target_agent_id": str(target_agent_id) if target_agent_id else None,
            })

            # Release the originating agent's slot
            if prev_agent_id is not None:
                await self._routing_engine.release_agent(
                    db, agent_id=prev_agent_id, tenant_id=conversation.tenant_id,
                )

    async def _handle_transfer_complete(
        self,
        db: AsyncSession,
        conversation: Conversation,
        metadata: dict,
    ) -> None:
        """Complete a pending transfer by assigning the target agent."""
        # Determine the target agent from metadata or from stored context
        target_agent_id_raw = metadata.get("target_agent_id") or (
            (conversation.context or {}).get("transfer_target_agent_id")
        )
        if target_agent_id_raw is None:
            raise ValueError(
                "Cannot complete transfer: no target_agent_id in metadata or conversation context"
            )

        target_agent_id = UUID(str(target_agent_id_raw))

        # Release the previous agent (for warm transfers the originating agent
        # was kept connected until now).
        prev_agent_id = conversation.current_handler_id
        if prev_agent_id is not None and prev_agent_id != target_agent_id:
            await self._routing_engine.release_agent(
                db, agent_id=prev_agent_id, tenant_id=conversation.tenant_id,
            )

        # Assign the target agent
        conversation.current_handler_type = "human"
        conversation.current_handler_id = target_agent_id
        conversation.sub_state = None

        await self._routing_engine.assign_agent(
            db, agent_id=target_agent_id, tenant_id=conversation.tenant_id,
        )

        # Clean up transfer context
        ctx = dict(conversation.context or {})
        ctx.pop("transfer_target_agent_id", None)
        ctx.pop("transfer_type", None)
        ctx.pop("transfer_initiated_by", None)
        conversation.context = ctx

    async def _handle_hold(
        self,
        db: AsyncSession,
        conversation: Conversation,
        metadata: dict,
    ) -> None:
        """Place the call on hold via the channel provider or LiveKit data channel."""
        conversation.sub_state = "on_hold"

        if conversation.channel == "voice":
            from app.config import settings
            if settings.use_livekit_agent and settings.livekit_url:
                # LiveKit path: signal the bridge to stop forwarding agent audio
                await self._send_room_data(conversation.id, {"type": "hold"})
            else:
                # Legacy path: instruct the telephony provider to play hold music
                try:
                    provider = await self._provider_registry.get_telephony(
                        conversation.tenant_id, db,
                    )
                    session_id = self._get_provider_session_id(conversation)
                    if provider and session_id:
                        hold_music_url = metadata.get("hold_music_url")
                        await provider.hold_call(session_id, hold_music_url=hold_music_url)
                except Exception:
                    logger.exception(
                        "Failed to place call on hold via provider "
                        "(conversation=%s, state=%s, tenant=%s)",
                        conversation.id,
                        conversation.state,
                        conversation.tenant_id,
                    )

    async def _handle_unhold(
        self,
        db: AsyncSession,
        conversation: Conversation,
        metadata: dict,
    ) -> None:
        """Resume the call from hold via the channel provider or LiveKit data channel."""
        conversation.sub_state = None

        if conversation.channel == "voice":
            from app.config import settings
            if settings.use_livekit_agent and settings.livekit_url:
                # LiveKit path: signal the bridge to resume forwarding
                await self._send_room_data(conversation.id, {"type": "unhold"})
            else:
                # Legacy path
                try:
                    provider = await self._provider_registry.get_telephony(
                        conversation.tenant_id, db,
                    )
                    session_id = self._get_provider_session_id(conversation)
                    if provider and session_id:
                        await provider.unhold_call(session_id)
                except Exception:
                    logger.exception(
                        "Failed to unhold call via provider "
                        "(conversation=%s, state=%s, tenant=%s)",
                        conversation.id,
                        conversation.state,
                        conversation.tenant_id,
                    )

    async def _handle_wrap_up(
        self,
        db: AsyncSession,
        conversation: Conversation,
        metadata: dict,
    ) -> None:
        """Move conversation into wrap-up / disposition phase."""
        # Signal LiveKit participants to disconnect (agent, bridge)
        await self._send_room_data(conversation.id, {
            "type": "call_ended",
            "reason": metadata.get("reason", "wrap_up"),
        })

        # Hang up the actual phone call via the telephony provider
        if conversation.channel == "voice":
            try:
                provider = await self._provider_registry.get_telephony(
                    conversation.tenant_id, db,
                )
                session_id = self._get_provider_session_id(conversation)
                if provider and session_id:
                    await provider.end_call(session_id)
            except Exception:
                logger.exception(
                    "Failed to hang up call via provider "
                    "(conversation=%s, state=%s, tenant=%s)",
                    conversation.id,
                    conversation.state,
                    conversation.tenant_id,
                )

        # Release the agent so they can take new conversations while filling
        # out the disposition form.
        prev_agent_id = conversation.current_handler_id
        if prev_agent_id is not None:
            await self._routing_engine.release_agent(
                db, agent_id=prev_agent_id, tenant_id=conversation.tenant_id,
            )

        conversation.current_handler_type = "system"
        conversation.current_handler_id = None
        conversation.sub_state = "awaiting_disposition"

    async def _handle_ended(
        self,
        db: AsyncSession,
        conversation: Conversation,
        metadata: dict,
    ) -> None:
        """Finalise the conversation: record timing, set disposition, and
        release any still-assigned agent."""
        now = datetime.now(timezone.utc)
        conversation.ended_at = now
        conversation.sub_state = None

        # Calculate duration
        if conversation.started_at:
            delta = now - conversation.started_at
            conversation.duration_seconds = int(delta.total_seconds())

        # Apply disposition from metadata if provided
        if "disposition" in metadata:
            conversation.disposition = metadata["disposition"]
        if "disposition_notes" in metadata:
            conversation.disposition_notes = metadata["disposition_notes"]

        # Release agent if one is still assigned
        if conversation.current_handler_id is not None:
            await self._routing_engine.release_agent(
                db,
                agent_id=conversation.current_handler_id,
                tenant_id=conversation.tenant_id,
            )

        conversation.current_handler_type = "system"
        conversation.current_handler_id = None

    async def _handle_failed(
        self,
        db: AsyncSession,
        conversation: Conversation,
        metadata: dict,
    ) -> None:
        """Handle a terminal failure (no answer, busy, error)."""
        now = datetime.now(timezone.utc)
        conversation.ended_at = now
        conversation.sub_state = None

        if conversation.started_at:
            delta = now - conversation.started_at
            conversation.duration_seconds = int(delta.total_seconds())

        # Store failure reason
        conversation.disposition = metadata.get("reason", "failed")

        # Release agent if somehow assigned
        if conversation.current_handler_id is not None:
            await self._routing_engine.release_agent(
                db,
                agent_id=conversation.current_handler_id,
                tenant_id=conversation.tenant_id,
            )

        conversation.current_handler_type = "system"
        conversation.current_handler_id = None

    # ------------------------------------------------------------------
    # LiveKit room data messaging
    # ------------------------------------------------------------------

    async def _send_room_data(
        self,
        conversation_id: UUID,
        data: dict,
        retries: int = 2,
    ) -> bool:
        """Send a data message to the LiveKit room for this conversation.

        Retries up to `retries` times with backoff. Returns True on success.
        Critical signals (handoff, agent_assigned) should check the return value.
        """
        from app.config import settings
        if not settings.use_livekit_agent or not settings.livekit_url:
            return True  # not applicable, consider success

        room_name = f"room-{conversation_id}"
        msg_type = data.get("type", "unknown")

        for attempt in range(1, retries + 2):  # 1-based, retries+1 total attempts
            try:
                from livekit import api as lk_api
                from livekit.protocol.models import DataPacket
                lk = lk_api.LiveKitAPI(
                    url=settings.livekit_url,
                    api_key=settings.livekit_api_key,
                    api_secret=settings.livekit_api_secret,
                )
                try:
                    await asyncio.wait_for(
                        lk.room.send_data(
                            lk_api.SendDataRequest(
                                room=room_name,
                                data=json.dumps(data).encode(),
                                kind=DataPacket.RELIABLE,
                                topic="bridge-control",
                            )
                        ),
                        timeout=2.0,
                    )
                    logger.info("Sent room data to %s: %s", room_name, msg_type)
                    return True
                finally:
                    await lk.aclose()
            except Exception:
                if attempt <= retries:
                    logger.warning(
                        "Room data send failed (attempt %d/%d, type=%s, room=%s), retrying...",
                        attempt, retries + 1, msg_type, room_name,
                    )
                    await asyncio.sleep(0.3 * attempt)
                else:
                    logger.error(
                        "Room data send FAILED after %d attempts (type=%s, room=%s)",
                        retries + 1, msg_type, room_name, exc_info=True,
                    )
        return False

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _load_conversation(
        self,
        db: AsyncSession,
        conversation_id: UUID,
    ) -> Conversation:
        """Load a conversation row with ``SELECT ... FOR UPDATE NOWAIT``."""
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.channel_sessions))
            .where(Conversation.id == conversation_id)
            .with_for_update(nowait=True)
        )
        try:
            result = await db.execute(stmt)
        except OperationalError as exc:
            # PostgreSQL error code 55P03 = lock_not_available
            if hasattr(exc.orig, "pgcode") and exc.orig.pgcode == "55P03":
                raise ConversationLockedError(conversation_id) from exc
            raise
        conversation = result.scalar_one_or_none()

        if conversation is None:
            raise ConversationNotFoundError(conversation_id)

        return conversation

    async def _create_handoff_event(
        self,
        db: AsyncSession,
        conversation: Conversation,
        event_type: str,
        from_handler_type: str | None,
        from_handler_id: UUID | None,
        to_handler_type: str | None,
        to_handler_id: UUID | None,
        from_state: str,
        to_state: str,
        reason: str | None,
        metadata: dict | None,
    ) -> HandoffEvent:
        """Create a ``HandoffEvent`` record and add it to the session."""
        handoff_event = HandoffEvent(
            conversation_id=conversation.id,
            tenant_id=conversation.tenant_id,
            event_type=event_type,
            from_handler_type=from_handler_type,
            from_handler_id=from_handler_id,
            to_handler_type=to_handler_type,
            to_handler_id=to_handler_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            context_snapshot=dict(conversation.context) if conversation.context else None,
            metadata_=metadata,
        )
        db.add(handoff_event)
        await db.flush()
        return handoff_event

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    async def _publish_event(
        self,
        conversation: Conversation,
        event_type: str,
        from_state: str,
        to_state: str,
        metadata: dict | None,
    ) -> None:
        """Publish an event to the in-process event bus.

        Topic naming convention:
        - ``conversation.state_changed`` — generic state transitions
        - ``conversation.handoff.<event_type>`` — specific handoff events
          (e.g. ``conversation.handoff.ivr_to_ai``)
        """
        # Determine topic
        handoff_event_types = {
            "ivr_to_ai",
            "ivr_to_human",
            "ai_to_human",
            "ai_confidence_drop",
            "customer_escalation",
            "handler_change",
            "human_to_human_cold",
            "human_to_human_warm",
            "transfer_completed",
            "transfer_failed",
            "hold_started",
            "hold_ended",
        }

        if event_type in handoff_event_types:
            topic = f"conversation.handoff.{event_type}"
        else:
            topic = "conversation.state_changed"

        event = Event(
            topic=topic,
            tenant_id=conversation.tenant_id,
            payload={
                "conversation_id": str(conversation.id),
                "from_state": from_state,
                "to_state": to_state,
                "event_type": event_type,
                "handler_type": conversation.current_handler_type,
                "handler_id": str(conversation.current_handler_id)
                if conversation.current_handler_id
                else None,
                "channel": conversation.channel,
                "customer_identifier": conversation.customer_identifier,
                "metadata": metadata or {},
            },
        )

        await self._event_bus.publish(event)

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _get_provider_session_id(conversation: Conversation) -> str | None:
        """Extract the active provider session ID from the conversation's
        channel sessions, if any are loaded."""
        if not hasattr(conversation, "channel_sessions") or not conversation.channel_sessions:
            return None
        # Return the most recent active session's provider ID
        for session in reversed(conversation.channel_sessions):
            if session.status not in ("ended", "failed", None):
                return session.provider_session_id
        # Fallback to the last session regardless of status
        return conversation.channel_sessions[-1].provider_session_id


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

handoff_engine = HandoffEngine(
    provider_registry=provider_registry,
    event_bus=event_bus,
    routing_engine=routing_engine,
    ai_engine=ai_engine,
    ivr_engine=ivr_engine,
    context_builder=context_builder,
)
