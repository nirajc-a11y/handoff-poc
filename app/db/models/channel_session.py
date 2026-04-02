import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, TenantScopedMixin, TimestampMixin


class ChannelSession(Base, PrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "channel_sessions"
    __table_args__ = (
        Index("ix_cs_provider_sid", "provider", "provider_session_id"),
        Index("ix_cs_conversation", "conversation_id"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    from_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="channel_sessions")


from app.db.models.conversation import Conversation  # noqa: E402, F811
