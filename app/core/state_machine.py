# Conversation state machine — pure-function transition table for the handoff engine.
# No side effects: given (state, trigger) returns (new_state, event_type) or raises.

from __future__ import annotations

from enum import Enum
from typing import Dict, Tuple


class ConversationState(str, Enum):
    INITIATED = "initiated"
    RINGING = "ringing"
    IVR = "ivr"
    AI_HANDLING = "ai_handling"
    QUEUED_FOR_HUMAN = "queued_for_human"
    HUMAN_HANDLING = "human_handling"
    ON_HOLD = "on_hold"
    TRANSFERRED = "transferred"
    WRAP_UP = "wrap_up"
    ENDED = "ended"
    FAILED = "failed"


class Trigger(str, Enum):
    # Call setup
    DIAL = "dial"
    RING = "ring"
    ANSWER = "answer"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    ERROR = "error"

    # IVR navigation
    DTMF_AI = "dtmf_ai"
    DTMF_HUMAN = "dtmf_human"
    DTMF_SUBMENU = "dtmf_submenu"

    # AI handling
    AI_CONFIDENCE_DROP = "ai_confidence_drop"
    CUSTOMER_ESCALATION = "customer_escalation"
    AI_RESOLVED = "ai_resolved"
    AI_TRANSFER = "ai_transfer"

    # Queue / agent assignment
    AGENT_ASSIGNED = "agent_assigned"
    QUEUE_TIMEOUT = "queue_timeout"

    # Hold
    AGENT_HOLD = "agent_hold"
    AGENT_UNHOLD = "agent_unhold"

    # Transfer
    COLD_TRANSFER = "cold_transfer"
    WARM_TRANSFER = "warm_transfer"
    TRANSFER_ACCEPTED = "transfer_accepted"
    TRANSFER_FAILED = "transfer_failed"

    # Ending
    AGENT_END = "agent_end"
    CUSTOMER_DISCONNECT = "customer_disconnect"
    DISPOSITION_SUBMITTED = "disposition_submitted"


# Maps (current_state, trigger) -> (new_state, event_type)
TRANSITIONS: Dict[
    Tuple[ConversationState, Trigger],
    Tuple[ConversationState, str],
] = {
    # -- Call setup --
    (ConversationState.INITIATED, Trigger.DIAL): (ConversationState.RINGING, "state_change"),
    (ConversationState.INITIATED, Trigger.RING): (ConversationState.RINGING, "state_change"),
    (ConversationState.RINGING, Trigger.ANSWER): (ConversationState.IVR, "state_change"),
    (ConversationState.RINGING, Trigger.NO_ANSWER): (ConversationState.FAILED, "state_change"),
    (ConversationState.RINGING, Trigger.BUSY): (ConversationState.FAILED, "state_change"),
    (ConversationState.RINGING, Trigger.ERROR): (ConversationState.FAILED, "state_change"),
    # -- IVR routing --
    (ConversationState.IVR, Trigger.DTMF_AI): (ConversationState.AI_HANDLING, "ivr_to_ai"),
    (ConversationState.IVR, Trigger.DTMF_HUMAN): (ConversationState.QUEUED_FOR_HUMAN, "ivr_to_human"),
    (ConversationState.IVR, Trigger.CUSTOMER_DISCONNECT): (ConversationState.WRAP_UP, "state_change"),
    (ConversationState.IVR, Trigger.AGENT_END): (ConversationState.WRAP_UP, "state_change"),
    # -- AI handling --
    (ConversationState.AI_HANDLING, Trigger.AI_CONFIDENCE_DROP): (ConversationState.QUEUED_FOR_HUMAN, "ai_confidence_drop"),
    (ConversationState.AI_HANDLING, Trigger.CUSTOMER_ESCALATION): (ConversationState.QUEUED_FOR_HUMAN, "customer_escalation"),
    (ConversationState.AI_HANDLING, Trigger.AI_RESOLVED): (ConversationState.WRAP_UP, "state_change"),
    (ConversationState.AI_HANDLING, Trigger.AI_TRANSFER): (ConversationState.QUEUED_FOR_HUMAN, "ai_to_human"),
    (ConversationState.AI_HANDLING, Trigger.CUSTOMER_DISCONNECT): (ConversationState.WRAP_UP, "state_change"),
    (ConversationState.AI_HANDLING, Trigger.AGENT_END): (ConversationState.WRAP_UP, "state_change"),
    # -- Queue --
    (ConversationState.QUEUED_FOR_HUMAN, Trigger.AGENT_ASSIGNED): (ConversationState.HUMAN_HANDLING, "handler_change"),
    (ConversationState.QUEUED_FOR_HUMAN, Trigger.QUEUE_TIMEOUT): (ConversationState.ENDED, "state_change"),
    (ConversationState.QUEUED_FOR_HUMAN, Trigger.CUSTOMER_DISCONNECT): (ConversationState.WRAP_UP, "state_change"),
    (ConversationState.QUEUED_FOR_HUMAN, Trigger.AGENT_END): (ConversationState.WRAP_UP, "state_change"),
    # -- Human handling / hold --
    (ConversationState.HUMAN_HANDLING, Trigger.AGENT_HOLD): (ConversationState.ON_HOLD, "hold_started"),
    (ConversationState.ON_HOLD, Trigger.AGENT_UNHOLD): (ConversationState.HUMAN_HANDLING, "hold_ended"),
    (ConversationState.ON_HOLD, Trigger.CUSTOMER_DISCONNECT): (ConversationState.WRAP_UP, "state_change"),
    (ConversationState.ON_HOLD, Trigger.AGENT_END): (ConversationState.WRAP_UP, "state_change"),
    # -- Transfers --
    (ConversationState.HUMAN_HANDLING, Trigger.COLD_TRANSFER): (ConversationState.TRANSFERRED, "human_to_human_cold"),
    (ConversationState.HUMAN_HANDLING, Trigger.WARM_TRANSFER): (ConversationState.TRANSFERRED, "human_to_human_warm"),
    (ConversationState.TRANSFERRED, Trigger.TRANSFER_ACCEPTED): (ConversationState.HUMAN_HANDLING, "transfer_completed"),
    (ConversationState.TRANSFERRED, Trigger.TRANSFER_FAILED): (ConversationState.HUMAN_HANDLING, "transfer_failed"),
    # -- Ending --
    (ConversationState.HUMAN_HANDLING, Trigger.AGENT_END): (ConversationState.WRAP_UP, "state_change"),
    (ConversationState.HUMAN_HANDLING, Trigger.CUSTOMER_DISCONNECT): (ConversationState.WRAP_UP, "state_change"),
    (ConversationState.WRAP_UP, Trigger.DISPOSITION_SUBMITTED): (ConversationState.ENDED, "state_change"),
    # -- Dead-end fixes --
    (ConversationState.FAILED, Trigger.CUSTOMER_DISCONNECT): (ConversationState.WRAP_UP, "state_change"),
    (ConversationState.TRANSFERRED, Trigger.CUSTOMER_DISCONNECT): (ConversationState.WRAP_UP, "state_change"),
    (ConversationState.TRANSFERRED, Trigger.QUEUE_TIMEOUT): (ConversationState.HUMAN_HANDLING, "transfer_timeout"),
    (ConversationState.IVR, Trigger.DTMF_SUBMENU): (ConversationState.IVR, "ivr_submenu"),
}


class StateMachineError(Exception):
    """Raised when a trigger is not valid for the current state."""

    def __init__(self, current_state: ConversationState, trigger: Trigger) -> None:
        self.current_state = current_state
        self.trigger = trigger
        super().__init__(
            f"Invalid transition: trigger {trigger!r} not allowed in state {current_state!r}"
        )


def transition(
    current_state: ConversationState,
    trigger: Trigger,
) -> tuple[ConversationState, str]:
    """Pure function: returns (new_state, event_type) or raises StateMachineError."""
    key = (current_state, trigger)
    result = TRANSITIONS.get(key)
    if result is None:
        raise StateMachineError(current_state, trigger)
    return result
