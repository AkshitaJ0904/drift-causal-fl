
"""ORM model for the durable trusted client key registry."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from core.supabase.base import Base


class TrustedKeyRecord(Base):
    """Persist trusted client public keys across process restarts and workers."""

    __tablename__ = "trusted_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    max_sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("key_id", name="uq_trusted_keys_key_id"),
        Index("ix_trusted_keys_client_id", "client_id"),
        Index("ix_trusted_keys_is_active", "is_active"),
    )
