import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, TenantScopedMixin


class Message(Base, PrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_msg_conv_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)  # customer, agent, ai, system, ivr
    sender_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)  # text, audio, image, file, dtmf, system_event
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)

    # Email threading
    email_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_in_reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


from app.db.models.conversation import Conversation  # noqa: E402, F811
