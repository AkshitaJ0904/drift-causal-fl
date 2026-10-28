
"""Database model for persistent federated-learning update approvals."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.supabase.base import Base


class UpdateApproval(Base):
    """Persist the approval lifecycle and payload identity of an update."""

    __tablename__ = "update_approvals"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    update_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)

    payload_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_approval",
        server_default="pending_approval",
    )

    reason: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "update_id",
            name="uq_update_approvals_client_update",
        ),
        CheckConstraint(
            "round_number >= 1",
            name="ck_update_approvals_positive_round",
        ),
        CheckConstraint(
            "status IN "
            "('validated', 'pending_approval', 'approved', "
            "'rejected', 'quarantined')",
            name="ck_update_approvals_valid_status",
        ),
        CheckConstraint(
            "length(payload_sha256) = 64",
            name="ck_update_approvals_payload_sha256_length",
        ),
        Index("ix_update_approvals_status", "status"),
        Index("ix_update_approvals_client_id", "client_id"),
        Index("ix_update_approvals_created_at", "created_at"),
    )
