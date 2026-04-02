from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TenantScopedMixin, TimestampMixin


class Lead(Base, PrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_tenant_phone", "tenant_id", "phone"),
        Index("ix_leads_tenant_email", "tenant_id", "email"),
    )

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)
