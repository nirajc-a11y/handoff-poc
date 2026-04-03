import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, TenantScopedMixin, TimestampMixin


class Conversation(Base, PrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conv_tenant_state", "tenant_id", "state"),
        Index("ix_conv_tenant_handler", "tenant_id", "current_handler_id"),
        Index("ix_conv_tenant_queue", "tenant_id", "state", "queue_priority"),
        Index("ix_conv_tenant_customer", "tenant_id", "customer_identifier"),
        Index("ix_conv_tenant_queue_time", "tenant_id", "queue_entered_at",
              postgresql_where=text("queue_entered_at IS NOT NULL")),
    )

    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # voice, whatsapp, email, sms
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # inbound, outbound

    # Participants
    customer_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True)
    campaign_lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign_leads.id"), nullable=True
    )

    # State machine
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="initiated", server_default=text("'initiated'"))
    sub_state: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Current handler
    current_handler_type: Mapped[str] = mapped_column(String(10), default="system")  # ivr, ai, human, system
    current_handler_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Queue tracking
    queue_entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    queue_priority: Mapped[int] = mapped_column(Integer, default=0)
    required_skills: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Timing
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Disposition
    disposition: Mapped[str | None] = mapped_column(String(100), nullable=True)
    disposition_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AI metadata
    ai_confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Recording
    recording_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Context accumulator
    context: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))

    # Relationships
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.created_at")
    handoff_events: Mapped[list["HandoffEvent"]] = relationship(
        back_populates="conversation", order_by="HandoffEvent.created_at"
    )
    channel_sessions: Mapped[list["ChannelSession"]] = relationship(back_populates="conversation")


from app.db.models.message import Message  # noqa: E402
from app.db.models.handoff_event import HandoffEvent  # noqa: E402
from app.db.models.channel_session import ChannelSession  # noqa: E402
