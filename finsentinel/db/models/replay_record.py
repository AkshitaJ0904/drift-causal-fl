
"""ORM model for the durable replay-protection store."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.supabase.base import Base


class ReplayRecord(Base):
    """One durable replay-protection record per (client_id, update_id) pair.

    Authoritative store that persists across process restarts and is
    shared across worker processes.  The unique constraint enforces that a
    given update identity can be reserved at most once.
    """

    __tablename__ = "replay_records"
    __table_args__ = (
        UniqueConstraint("client_id", "update_id", name="uq_replay_client_update"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    update_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    finalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
