"""Transactional audit-event outbox for durable external delivery.

Usage pattern
-------------
1. Within a business transaction (e.g. ``_transition()`` in approval_service),
   call ``enqueue(db, ...)`` to stage an outbox record.  It is committed
   atomically with the business state change.

2. A delivery worker calls ``deliver_pending_events(delivery_fn=...)`` to
   claim a batch, attempt delivery, and mark each record delivered or release
   it for retry with exponential back-off.

3. If no external destination is configured, ``deliver_pending_events``
   returns without marking anything delivered.  Records remain pending so
   they can be delivered later when a destination is wired up.

Concurrency semantics
---------------------
On **PostgreSQL** the claim query uses ``SELECT FOR UPDATE SKIP LOCKED`` so
concurrent workers never deliver the same event simultaneously.  On
**SQLite** (used in tests) this lock clause is a no-op; SQLite's
single-writer model already serialises access, so single-threaded test
correctness is preserved.

``idempotency_key`` is generated once at enqueue time and reused on every
retry, allowing a receiver to deduplicate safely.

Retry and dead-letter policy
----------------------------
When ``deliver_pending_events`` is called with a non-None ``delivery_fn`` and
delivery raises, ``release_claim_with_backoff`` is called:

- Each failure increments ``attempt_count`` and sets ``retry_after`` to
  ``now + min(backoff_base * 2^(attempt_count - 1), 3600)`` seconds.
- After ``MAX_DELIVERY_ATTEMPTS`` (default 10) failures the record is moved
  to the ``dead_letter`` status so it no longer clogs the pending queue.
- Dead-lettered records are **never silently deleted**.  They require manual
  inspection or a separate dead-letter reprocessing path.

When ``delivery_fn`` is ``None`` (no destination configured), no backoff and
no dead-lettering is applied — records remain perpetually pending.

Calling ``release_claim`` directly (without backoff) leaves ``retry_after``
as ``None``, which means the record is immediately reclaimable.  This
intentional design keeps unit tests that call ``release_claim`` directly
unaffected by the backoff policy.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from audit.delivery import SCHEMA_VERSION, SERVICE_NAME, DeliveryPermanentError
from db.models.audit_outbox import AuditOutboxRecord

logger = logging.getLogger(__name__)

_DEFAULT_CLAIM_TTL_SECONDS = 60
_DEFAULT_BATCH_LIMIT = 50
MAX_DELIVERY_ATTEMPTS = 10
_DEFAULT_BACKOFF_BASE_SECONDS = 60  # doubles per attempt, capped at 3600 s


@dataclass(frozen=True)
class _ClaimedSnapshot:
    """Immutable snapshot of an outbox record captured while the DB session is open.

    Storing plain Python values avoids accessing detached SQLAlchemy instances
    after the claim transaction closes.
    """

    db_id: int
    payload: dict[str, Any]


def enqueue(
    db: Session,
    *,
    event_id: int | None,
    event_type: str,
    severity: str,
    description: str,
    client_id: str | None,
    update_id: str | None,
) -> AuditOutboxRecord:
    """Stage an outbox record within an *existing* database session.

    Does **not** commit — the caller owns the transaction.  The record is
    committed atomically with whatever the caller commits next.

    Parameters
    ----------
    db:
        Open SQLAlchemy session that is part of the caller's transaction.
    event_id:
        FK reference to the ``audit_events`` row, if one was already flushed.
    event_type, severity, description, client_id, update_id:
        Snapshot of the audit event fields stored directly in the outbox row
        so delivery does not need to re-query ``audit_events``.
    """
    record = AuditOutboxRecord(
        idempotency_key=uuid.uuid4().hex,
        event_id=event_id,
        event_type=event_type,
        severity=severity,
        description=description,
        client_id=client_id,
        update_id=update_id,
        status="pending",
        attempt_count=0,
        claimed_until=None,
        delivered_at=None,
    )
    db.add(record)
    return record


def _pending_or_expired_claim(now: datetime):
    """Filter for records eligible to be claimed.

    A record is eligible when:
    - status == 'pending' AND (retry_after IS NULL OR retry_after <= now), OR
    - status == 'claimed' AND claimed_until IS NOT NULL AND claimed_until < now
      (expired claim — worker that held it crashed or timed out).
    """
    return or_(
        and_(
            AuditOutboxRecord.status == "pending",
            or_(
                AuditOutboxRecord.retry_after.is_(None),
                AuditOutboxRecord.retry_after <= now,
            ),
        ),
        and_(
            AuditOutboxRecord.status == "claimed",
            AuditOutboxRecord.claimed_until.is_not(None),
            AuditOutboxRecord.claimed_until < now,
        ),
    )


def claim_pending_batch(
    db: Session,
    *,
    limit: int = _DEFAULT_BATCH_LIMIT,
    claim_ttl_seconds: int = _DEFAULT_CLAIM_TTL_SECONDS,
) -> list[AuditOutboxRecord]:
    """Claim up to *limit* eligible outbox records within the caller's transaction.

    Sets ``status='claimed'`` and ``claimed_until`` on each record.
    On PostgreSQL, uses ``SELECT FOR UPDATE SKIP LOCKED`` to prevent two
    workers from claiming the same record simultaneously.  On SQLite (tests),
    no row-level lock is applied.

    The caller must commit the transaction for the claims to be visible to
    other sessions.  The caller is responsible for delivering each claimed
    record and calling ``mark_delivered`` or ``release_claim`` as appropriate.
    """
    now = datetime.now(tz=UTC)
    deadline = now + timedelta(seconds=claim_ttl_seconds)

    q = (
        select(AuditOutboxRecord)
        .where(_pending_or_expired_claim(now))
        .order_by(AuditOutboxRecord.id)
        .limit(limit)
    )

    # Apply FOR UPDATE SKIP LOCKED on PostgreSQL only.
    # SQLite does not support row-level locking; single-writer semantics are
    # sufficient for test correctness.
    try:
        engine = db.get_bind()
        if engine.dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True)
    except Exception:
        pass  # Defensive: if dialect detection fails, proceed without locking.

    rows = db.execute(q).scalars().all()

    for row in rows:
        row.status = "claimed"
        row.claimed_until = deadline
        row.attempt_count = (row.attempt_count or 0) + 1

    db.flush()
    return list(rows)


def mark_delivered(db: Session, record: AuditOutboxRecord) -> None:
    """Mark a claimed record as successfully delivered.

    Must be called only after durable external delivery has been confirmed.
    """
    record.status = "delivered"
    record.delivered_at = datetime.now(tz=UTC)
    record.claimed_until = None
    db.flush()


def release_claim(db: Session, record: AuditOutboxRecord) -> None:
    """Release a claimed record back to pending with no backoff applied.

    ``retry_after`` is left unchanged (typically NULL), meaning the record
    is immediately reclaimable.  Use this when delivery was not attempted
    (e.g. no destination is configured) so dead-letter logic is not triggered.
    For failed delivery attempts use ``release_claim_with_backoff`` instead.
    """
    record.status = "pending"
    record.claimed_until = None
    db.flush()


def release_claim_with_backoff(
    db: Session,
    record: AuditOutboxRecord,
    *,
    max_attempts: int = MAX_DELIVERY_ATTEMPTS,
    backoff_base_seconds: int = _DEFAULT_BACKOFF_BASE_SECONDS,
    _now: datetime | None = None,
) -> None:
    """Release a claimed record after a failed delivery attempt.

    Applies exponential backoff and moves the record to ``dead_letter``
    status once ``max_attempts`` is reached.

    Parameters
    ----------
    max_attempts:
        Total delivery failures before the record is dead-lettered.
    backoff_base_seconds:
        Base for the exponential delay: ``min(base * 2^(attempt-1), 3600) s``.
    _now:
        Wall-clock override for testing; defaults to ``datetime.now(UTC)``.
    """
    now = _now or datetime.now(tz=UTC)
    attempts = record.attempt_count or 0

    if attempts >= max_attempts:
        record.status = "dead_letter"
        record.claimed_until = None
        record.retry_after = None
        logger.error(
            "Outbox record id=%d idempotency_key=%s type=%s reached max attempts "
            "(%d); moving to dead_letter. Manual intervention required.",
            record.id,
            record.idempotency_key,
            record.event_type,
            max_attempts,
        )
    else:
        backoff = min(backoff_base_seconds * (2 ** (attempts - 1)), 3600)
        record.status = "pending"
        record.claimed_until = None
        record.retry_after = now + timedelta(seconds=backoff)
        logger.warning(
            "Outbox record id=%d type=%s delivery failed (attempt %d/%d); "
            "retry_after=%s (backoff=%ds).",
            record.id,
            record.event_type,
            attempts,
            max_attempts,
            record.retry_after.isoformat(),
            backoff,
        )

    db.flush()


def dead_letter_count() -> int:
    """Return the number of dead-lettered outbox records."""
    from core.supabase.session import SessionLocal  # noqa: PLC0415

    with SessionLocal() as db:
        result = db.scalar(
            select(func.count(AuditOutboxRecord.id)).where(
                AuditOutboxRecord.status == "dead_letter"
            )
        )
        return result or 0


def deliver_pending_events(
    *,
    max_events: int = _DEFAULT_BATCH_LIMIT,
    delivery_fn: Callable[[dict[str, Any]], None] | None = None,
    claim_ttl_seconds: int = _DEFAULT_CLAIM_TTL_SECONDS,
    max_attempts: int = MAX_DELIVERY_ATTEMPTS,
) -> dict[str, int]:
    """Claim and deliver a batch of pending outbox records.

    Uses a **three-phase** design when a delivery function is configured so
    that no database transaction is held open during network I/O:

    1. **Claim phase** (short transaction): claim up to *max_events* records,
       snapshot their data, commit.
    2. **Delivery phase** (outside any transaction): call *delivery_fn* for
       each record.  Network latency cannot extend a DB transaction.
    3. **Acknowledge phase** (short transaction): mark each record delivered
       or release it back to pending with backoff.

    When *delivery_fn* is ``None`` the claim and release happen in a single
    transaction (no network I/O, no three-phase split needed).

    Parameters
    ----------
    max_events:
        Maximum number of records to claim in this call.
    delivery_fn:
        Callable that receives the event payload dict.  Raising any exception
        signals delivery failure; the record gets backoff and eventual
        dead-lettering.  Raising ``DeliveryPermanentError`` bypasses backoff
        and dead-letters the record immediately (used for HTTP 4xx responses).
        If ``None``, claimed records are released immediately with no backoff.
    claim_ttl_seconds:
        How long a claim is held before it expires and becomes reclaimable.
    max_attempts:
        Maximum delivery attempts before dead-lettering.

    Returns
    -------
    dict with keys ``"claimed"``, ``"delivered"``, ``"released"``,
    ``"dead_lettered"`` with integer counts.
    """
    from core.supabase.session import SessionLocal  # local import to avoid circular

    counts = {"claimed": 0, "delivered": 0, "released": 0, "dead_lettered": 0}

    if delivery_fn is None:
        # No delivery fn: claim and immediately release without backoff.
        # Records remain perpetually pending without triggering dead-letter logic.
        with SessionLocal() as db:
            with db.begin():
                records = claim_pending_batch(
                    db, limit=max_events, claim_ttl_seconds=claim_ttl_seconds
                )
                counts["claimed"] = len(records)
                for record in records:
                    release_claim(db, record)
                    counts["released"] += 1
        return counts

    # --- Three-phase delivery ---

    # Phase 1: Claim records. Snapshot payload data while the session is open,
    # then commit the claims.  No network I/O happens inside this transaction.
    snapshots: list[_ClaimedSnapshot] = []

    with SessionLocal() as db:
        with db.begin():
            records = claim_pending_batch(
                db, limit=max_events, claim_ttl_seconds=claim_ttl_seconds
            )
            counts["claimed"] = len(records)

            for record in records:
                created_iso: str | None = None
                if record.created_at is not None:
                    created_iso = record.created_at.isoformat()

                snapshots.append(
                    _ClaimedSnapshot(
                        db_id=record.id,
                        payload={
                            "schema_version": SCHEMA_VERSION,
                            "service": SERVICE_NAME,
                            "idempotency_key": record.idempotency_key,
                            "event_id": record.event_id,
                            "event_type": record.event_type,
                            "severity": record.severity,
                            "client_id": record.client_id,
                            "update_id": record.update_id,
                            "description": record.description,
                            "attempt_count": record.attempt_count,
                            "created_at": created_iso,
                        },
                    )
                )
    # DB transaction committed here.  Claim is durable.

    if not snapshots:
        return counts

    # Phase 2: Deliver outside any DB transaction.
    outcomes: list[tuple[int, str]] = []  # (db_id, "delivered" | "failed" | "permanent_fail")

    for snap in snapshots:
        try:
            delivery_fn(snap.payload)
            outcomes.append((snap.db_id, "delivered"))
            # counts["delivered"] incremented in Phase 3 after mark_delivered succeeds.
        except DeliveryPermanentError:
            logger.exception(
                "Permanent delivery failure for outbox record id=%d type=%s — "
                "dead-lettering immediately (4xx response, non-retryable).",
                snap.db_id,
                snap.payload.get("event_type"),
            )
            outcomes.append((snap.db_id, "permanent_fail"))
        except Exception:
            logger.exception(
                "Transient delivery failure for outbox record id=%d type=%s.",
                snap.db_id,
                snap.payload.get("event_type"),
            )
            outcomes.append((snap.db_id, "failed"))

    # Phase 3: Acknowledge each record in its own mini-transaction.
    # Per-record isolation means a failure on one record does not roll back acks
    # for others.  When mark_delivered itself fails (e.g. a DB write error after
    # a successful external delivery), a fallback transaction applies
    # release_claim_with_backoff so the record retries instead of remaining
    # perpetually claimed until the TTL expires.
    for record_id, outcome in outcomes:
        if outcome == "delivered":
            try:
                with SessionLocal() as db:
                    with db.begin():
                        rec: AuditOutboxRecord | None = db.get(AuditOutboxRecord, record_id)
                        if rec is None:
                            logger.warning(
                                "Outbox record id=%d vanished before ack.", record_id
                            )
                            continue
                        mark_delivered(db, rec)
                        counts["delivered"] += 1
            except Exception:
                logger.exception(
                    "mark_delivered failed for outbox record id=%d; "
                    "applying backoff so the record will be re-delivered.",
                    record_id,
                )
                # Fallback: open a fresh session, reload, and apply backoff.
                # The delivery WAS sent; the receiver will see a duplicate on
                # retry and must deduplicate via idempotency_key.
                try:
                    with SessionLocal() as db:
                        with db.begin():
                            rec = db.get(AuditOutboxRecord, record_id)
                            if rec is not None and rec.status == "claimed":
                                release_claim_with_backoff(
                                    db, rec, max_attempts=max_attempts
                                )
                                if rec.status == "dead_letter":
                                    counts["dead_lettered"] += 1
                                else:
                                    counts["released"] += 1
                except Exception:
                    logger.exception(
                        "Fallback ack also failed for outbox record id=%d; "
                        "record will be re-claimed when its claim TTL expires.",
                        record_id,
                    )

        elif outcome == "permanent_fail":
            try:
                with SessionLocal() as db:
                    with db.begin():
                        rec = db.get(AuditOutboxRecord, record_id)
                        if rec is None:
                            continue
                        # Force dead-letter immediately: set attempt_count to max
                        # so release_claim_with_backoff transitions to dead_letter.
                        rec.attempt_count = max_attempts
                        release_claim_with_backoff(db, rec, max_attempts=max_attempts)
                        counts["dead_lettered"] += 1
            except Exception:
                logger.exception(
                    "Failed to dead-letter outbox record id=%d after permanent delivery "
                    "failure; claim will expire and be re-tried.",
                    record_id,
                )

        else:  # "failed"
            try:
                with SessionLocal() as db:
                    with db.begin():
                        rec = db.get(AuditOutboxRecord, record_id)
                        if rec is None:
                            continue
                        release_claim_with_backoff(db, rec, max_attempts=max_attempts)
                        if rec.status == "dead_letter":
                            counts["dead_lettered"] += 1
                        else:
                            counts["released"] += 1
            except Exception:
                logger.exception(
                    "Failed to release outbox record id=%d after delivery failure; "
                    "claim will expire and be re-tried.",
                    record_id,
                )

    return counts


def pending_count() -> int:
    """Return the number of pending (not yet delivered) outbox records."""
    from core.supabase.session import SessionLocal

    with SessionLocal() as db:
        result = db.scalar(
            select(func.count(AuditOutboxRecord.id)).where(
                AuditOutboxRecord.status.in_(["pending", "claimed"])
            )
        )
        return result or 0
