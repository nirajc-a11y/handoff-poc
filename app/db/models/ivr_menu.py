import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TenantScopedMixin, TimestampMixin


class IVRMenu(Base, PrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "ivr_menus"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_root: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    options: Mapped[list["IVRMenuOption"]] = relationship(back_populates="menu", order_by="IVRMenuOption.sort_order")


class IVRMenuOption(Base, PrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "ivr_menu_options"
    __table_args__ = (UniqueConstraint("menu_id", "digit"),)

    menu_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ivr_menus.id"), nullable=False)
    digit: Mapped[str] = mapped_column(String(5), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)  # submenu, ai_handoff, human_queue, play_message, hangup
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_config: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    menu: Mapped["IVRMenu"] = relationship(back_populates="options")
