
"""Database model for persistent federated-learning update approvals."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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
    sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_count_provenance: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default="client_claimed",
        server_default="client_claimed",
    )

    payload_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    risk_score: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    risk_severity: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )
    suspicious: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    anomaly_reasons: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    detector_version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    detector_config: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    audit_status: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )
    audit_failures: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
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
            "sample_count IS NULL OR sample_count > 0",
            name="ck_update_approvals_positive_sample_count",
        ),
        CheckConstraint(
            "sample_count_provenance IS NULL OR sample_count_provenance IN "
            "('client_claimed', 'provider_verified')",
            name="ck_update_approvals_sample_count_provenance",
        ),
        CheckConstraint(
            "status IN "
            "('validated', 'pending_approval', 'approved', "
            "'rejected', 'quarantined')",
            name="ck_update_approvals_valid_status",
        ),
        CheckConstraint(
            "payload_sha256 IS NULL OR length(payload_sha256) = 64",
            name="ck_update_approvals_payload_sha256_format",
        ),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)",
            name="ck_update_approvals_risk_score_range",
        ),
        CheckConstraint(
            "risk_severity IS NULL OR risk_severity IN "
            "('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_update_approvals_risk_severity",
        ),
        CheckConstraint(
            "audit_status IS NULL OR audit_status IN "
            "('pending', 'persisted', 'failed')",
            name="ck_update_approvals_audit_status",
        ),
        Index("ix_update_approvals_status", "status"),
        Index("ix_update_approvals_client_id", "client_id"),
        Index("ix_update_approvals_created_at", "created_at"),
    )
