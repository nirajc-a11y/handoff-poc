from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentStatusEnum(str, Enum):
    available = "available"
    busy = "busy"
    offline = "offline"
    on_call = "on_call"
    break_ = "break"


class ChannelEnum(str, Enum):
    voice = "voice"
    whatsapp = "whatsapp"
    email = "email"
    sms = "sms"


class DirectionEnum(str, Enum):
    inbound = "inbound"
    outbound = "outbound"


class HandlerTypeEnum(str, Enum):
    ivr = "ivr"
    ai = "ai"
    human = "human"
    system = "system"


class CampaignStatusEnum(str, Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"


class CampaignTypeEnum(str, Enum):
    outbound_call = "outbound_call"
    outbound_sms = "outbound_sms"


class CampaignLeadStatusEnum(str, Enum):
    pending = "pending"
    assigned = "assigned"
    attempted = "attempted"
    completed = "completed"
    failed = "failed"


class SenderTypeEnum(str, Enum):
    customer = "customer"
    agent = "agent"
    ai = "ai"
    system = "system"


class ContentTypeEnum(str, Enum):
    text = "text"
    audio = "audio"
    image = "image"


class IVRActionTypeEnum(str, Enum):
    submenu = "submenu"
    ai_handoff = "ai_handoff"
    human_queue = "human_queue"
    play_message = "play_message"
    hangup = "hangup"


class UserRoleEnum(str, Enum):
    agent = "agent"
    supervisor = "supervisor"
    admin = "admin"


class TenantStatusEnum(str, Enum):
    active = "active"
    suspended = "suspended"


class SupervisorModeEnum(str, Enum):
    listen = "listen"
    barge = "barge"


class TelephonyProviderEnum(str, Enum):
    twilio = "twilio"
    plivo = "plivo"


# ---------------------------------------------------------------------------
# Annotated types
# ---------------------------------------------------------------------------

PhoneNumber = Annotated[str, Field(pattern=r"^\+?[1-9]\d{6,14}$", max_length=30)]
NameStr = Annotated[str, Field(min_length=1, max_length=255)]
ShortStr = Annotated[str, Field(min_length=1, max_length=100)]
SlugStr = Annotated[str, Field(min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")]


# ---------------------------------------------------------------------------
# Error model
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class AgentProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    skills: list | None = None
    max_concurrent: int
    team: str | None = None

    @field_serializer("id", "user_id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class AgentStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    status: str
    current_conversations: int
    last_status_change: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("id", "agent_id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    skills: list | None = None
    max_concurrent: int
    team: str | None = None
    status: AgentStatusResponse | None = None

    @field_serializer("id", "user_id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    role: str
    is_active: bool
    tenant_id: UUID

    @field_serializer("id", "tenant_id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    config: dict | None = None
    status: str | None = None

    @field_serializer("id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: UUID
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    whatsapp_number: str | None = None
    metadata: dict | None = Field(None, validation_alias="metadata_")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("id", "tenant_id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    type: str
    status: str
    config: dict | None = None
    start_date: date | None = None
    end_date: date | None = None
    created_at: datetime | None = None

    @field_serializer("id", "tenant_id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class CampaignLeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    lead_id: UUID
    status: str
    assigned_agent_id: UUID | None = None
    attempts: int
    last_attempt_at: datetime | None = None

    @field_serializer("id", "campaign_id", "lead_id", "assigned_agent_id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class IVRMenuOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    menu_id: UUID
    digit: str
    label: str | None = None
    action_type: str
    target_id: UUID | None = None
    target_config: dict | None = None

    @field_serializer("id", "menu_id", "target_id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class IVRMenuResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    is_root: bool
    welcome_message: str | None = None
    config: dict | None = None
    options: list[IVRMenuOptionResponse] = []

    @field_serializer("id", "tenant_id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    content: str | None = None
    content_type: str
    sender_type: str
    sender_id: UUID | None = None
    created_at: datetime | None = None

    @field_serializer("id", "conversation_id", "sender_id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class HandoffEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    event_type: str
    from_state: str | None = None
    to_state: str | None = None
    from_handler_type: str | None = None
    to_handler_type: str | None = None
    reason: str | None = None
    created_at: datetime | None = None

    @field_serializer("id", "conversation_id")
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    channel: str
    direction: str
    state: str
    sub_state: str | None = None
    customer_identifier: str | None = None
    customer_name: str | None = None
    current_handler_type: str | None = None
    current_handler_id: UUID | None = None
    lead_id: UUID | None = None
    campaign_lead_id: UUID | None = None
    started_at: datetime | None = None
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    disposition: str | None = None
    disposition_notes: str | None = None
    context: dict | None = None
    queue_priority: int | None = None
    required_skills: list | None = None
    created_at: datetime | None = None

    @field_serializer(
        "id", "tenant_id", "current_handler_id", "lead_id", "campaign_lead_id"
    )
    def _uuid_to_str(self, v: UUID | None) -> str | None:
        return str(v) if v is not None else None


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse] = []
    handoff_events: list[HandoffEventResponse] = []
