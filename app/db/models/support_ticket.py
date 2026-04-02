import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TenantScopedMixin, TimestampMixin


class SupportTicket(Base, PrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "support_tickets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ticket_number"),
        Index("ix_st_tenant_status", "tenant_id", "status"),
    )

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True
    )
    ticket_number: Mapped[str] = mapped_column(String(50), nullable=False)
    customer_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open")
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_profiles.id"), nullable=True
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSONB, default=list)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
