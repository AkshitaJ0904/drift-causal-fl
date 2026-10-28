
"""Database model for FinSentinel security audit events."""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.supabase.base import Base


class AuditEvent(Base):
    """Record security-relevant events for investigation and auditing."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="info",
    )
    client_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    update_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
    )
