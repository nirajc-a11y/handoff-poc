import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, TenantScopedMixin


class HandoffEvent(Base, PrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "handoff_events"
    __table_args__ = (
        Index("ix_he_conv_created", "conversation_id", "created_at"),
        Index("ix_he_tenant_type_created", "tenant_id", "event_type", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)

    from_handler_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    from_handler_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    to_handler_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    to_handler_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    from_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(50), nullable=True)

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="handoff_events")


from app.db.models.conversation import Conversation  # noqa: E402, F811
