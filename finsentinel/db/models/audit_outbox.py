
"""ORM model for the transactional audit-event outbox.

Outbox records are written atomically with the business state change that
generates the audit event.  A separate delivery process claims pending
records, delivers them to a configured external destination, and marks them
delivered only after success.  Unclaimed or failed records remain pending so
they can be retried safely.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from core.supabase.base import Base


class AuditOutboxRecord(Base):
    """Pending or delivered audit event awaiting external delivery."""

    __tablename__ = "audit_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Stable identifier reused on every delivery attempt so the receiver can
    # deduplicate.  Generated once at INSERT, never changed.
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # Nullable FK — may be NULL when the outbox record is enqueued before the
    # AuditEvent row is flushed (should not happen with current code paths, but
    # kept nullable for forward-compatibility).
    event_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("audit_events.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Event payload snapshot — avoids re-querying the AuditEvent on delivery.
    # Description is included but must NOT contain private-key material or
    # raw model weights; callers are responsible for sanitizing descriptions.
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    update_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Delivery lifecycle fields.
    # status: 'pending' → 'claimed' → 'delivered' | back to 'pending' on failure
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # When non-NULL the record is claimed until this deadline; expired claims
    # are eligible for re-claim by any worker.
    claimed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Earliest wall-clock time the record may be re-claimed after a failed
    # delivery attempt.  NULL means immediately claimable (new record or no
    # backoff applied).  Set by release_claim_with_backoff(); never set by
    # release_claim() so unit tests that call that function directly are
    # unaffected.
    retry_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_audit_outbox_idempotency_key"),
        Index("ix_audit_outbox_status", "status"),
        Index("ix_audit_outbox_claimed_until", "claimed_until"),
        Index("ix_audit_outbox_retry_after", "retry_after"),
    )
