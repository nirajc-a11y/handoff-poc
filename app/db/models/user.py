import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, TenantScopedMixin, TimestampMixin


class User(Base, PrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email"),)

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # agent, supervisor, admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    agent_profile: Mapped["AgentProfile | None"] = relationship(back_populates="user", uselist=False)


class AgentProfile(Base, PrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "agent_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True
    )
    skills: Mapped[dict | None] = mapped_column(JSONB, default=list)
    max_concurrent: Mapped[int] = mapped_column(Integer, default=1)
    team: Mapped[str | None] = mapped_column(String(100), nullable=True)

    user: Mapped["User"] = relationship(back_populates="agent_profile")
    status: Mapped["AgentStatus | None"] = relationship(back_populates="agent", uselist=False)


class AgentStatus(Base, PrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "agent_statuses"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_profiles.id"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(20), default="offline", server_default=text("'offline'"))
    current_conversations: Mapped[int] = mapped_column(Integer, default=0)
    last_status_change: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped["AgentProfile"] = relationship(back_populates="status")
