"""Tests for the transactional audit-event outbox (audit/outbox.py).

Coverage:
 - Enqueue stages a record within an existing session
 - Rollback of business transaction also rolls back the outbox record
 - Delivery succeeds: record marked delivered; idempotency_key stable
 - Delivery failure: record released back to pending for retry
 - Claim expiry: expired claimed records reclaimable
 - Already-delivered records not re-claimed
 - Duplicate delivery prevention: second claim doesn't re-claim delivered event
 - Restart-equivalent persistence: records survive across session boundaries
 - Concurrent delivery (sequential simulation): same event not claimed twice
   in the same batch
 - audit/service.record_audit_event enqueues atomically in same transaction
 - enforcement/approval_service._transition enqueues atomically with state change
 - deliver_pending_events with no delivery_fn retains events as pending
 - deliver_pending_events with delivery_fn marks events delivered
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from audit.outbox import (
    MAX_DELIVERY_ATTEMPTS,
    claim_pending_batch,
    dead_letter_count,
    deliver_pending_events,
    enqueue,
    mark_delivered,
    pending_count,
    release_claim,
    release_claim_with_backoff,
)
from audit.service import record_audit_event
from core.supabase.session import SessionLocal
from db.models.audit_outbox import AuditOutboxRecord
from enforcement.approval_service import (
    approve_update,
    record_ingestion_audit_result,
    register_validated_update,
)
from ingestion.sample_count_provider import PROVENANCE_CLIENT_CLAIMED, SampleCountResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _clear_outbox() -> None:
    from sqlalchemy import delete

    with SessionLocal() as db:
        db.execute(delete(AuditOutboxRecord))
        db.commit()


@pytest.fixture(autouse=True)
def _reset_outbox():
    _clear_outbox()
    yield
    _clear_outbox()


def _clear_approvals() -> None:
    from sqlalchemy import delete

    from db.models.audit_event import AuditEvent
    from db.models.replay_record import ReplayRecord
    from db.models.update_approval import UpdateApproval

    with SessionLocal() as db:
        db.execute(delete(AuditOutboxRecord))
        db.execute(delete(AuditEvent))
        db.execute(delete(UpdateApproval))
        db.execute(delete(ReplayRecord))
        db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enqueue_one(
    event_type: str = "test.event",
    severity: str = "info",
    description: str = "test description",
    client_id: str | None = "client-001",
    update_id: str | None = "update-001",
) -> AuditOutboxRecord:
    """Enqueue and commit a single outbox record; return it."""
    with SessionLocal() as db:
        with db.begin():
            record = enqueue(
                db,
                event_id=None,
                event_type=event_type,
                severity=severity,
                description=description,
                client_id=client_id,
                update_id=update_id,
            )
            db.flush()
    with SessionLocal() as db:
        result = db.get(AuditOutboxRecord, record.id)
    assert result is not None
    return result


# ---------------------------------------------------------------------------
# Basic enqueue and status
# ---------------------------------------------------------------------------


def test_enqueue_creates_pending_record() -> None:
    record = _enqueue_one()

    assert record is not None
    assert record.status == "pending"
    assert record.attempt_count == 0
    assert record.claimed_until is None
    assert record.delivered_at is None


def test_enqueue_generates_unique_idempotency_keys() -> None:
    r1 = _enqueue_one(event_type="type.a")
    r2 = _enqueue_one(event_type="type.b")

    assert r1.idempotency_key != r2.idempotency_key


def test_enqueue_stores_event_fields() -> None:
    record = _enqueue_one(
        event_type="security.test",
        severity="high",
        description="Test event",
        client_id="c-1",
        update_id="u-1",
    )

    assert record.event_type == "security.test"
    assert record.severity == "high"
    assert record.description == "Test event"
    assert record.client_id == "c-1"
    assert record.update_id == "u-1"


# ---------------------------------------------------------------------------
# Rollback: outbox record rolled back with business transaction
# ---------------------------------------------------------------------------


def test_rollback_removes_outbox_record() -> None:
    """When the enclosing transaction rolls back, the outbox record is not persisted."""
    with SessionLocal() as db:
        try:
            with db.begin():
                enqueue(
                    db,
                    event_id=None,
                    event_type="test.rollback",
                    severity="info",
                    description="should not persist",
                    client_id=None,
                    update_id=None,
                )
                raise RuntimeError("simulated business failure")
        except RuntimeError:
            pass  # transaction rolled back

    assert pending_count() == 0


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------


def test_claim_pending_batch_claims_record() -> None:
    _enqueue_one()

    with SessionLocal() as db:
        with db.begin():
            claimed = claim_pending_batch(db, limit=10)

    assert len(claimed) == 1
    assert claimed[0].status == "claimed"
    assert claimed[0].attempt_count == 1
    assert claimed[0].claimed_until is not None


def test_claim_increments_attempt_count_on_retry() -> None:
    record = _enqueue_one()
    record_id = record.id

    # First claim, then release, then claim again.
    with SessionLocal() as db:
        with db.begin():
            [r] = claim_pending_batch(db, limit=1)
            release_claim(db, r)

    with SessionLocal() as db:
        with db.begin():
            [r] = claim_pending_batch(db, limit=1)

    with SessionLocal() as db:
        reloaded = db.get(AuditOutboxRecord, record_id)
    assert reloaded is not None
    assert reloaded.attempt_count == 2


def test_claimed_record_not_re_claimed_before_expiry() -> None:
    _enqueue_one()

    with SessionLocal() as db:
        with db.begin():
            first_batch = claim_pending_batch(db, limit=1, claim_ttl_seconds=600)

    # Attempt a second claim while the record is still claimed.
    with SessionLocal() as db:
        with db.begin():
            second_batch = claim_pending_batch(db, limit=1)

    assert len(first_batch) == 1
    assert len(second_batch) == 0


def test_expired_claimed_record_is_reclaimable(monkeypatch) -> None:
    """A claimed record whose claimed_until is in the past can be re-claimed."""
    record = _enqueue_one()
    record_id = record.id

    # Manually set claimed_until to the past to simulate expiry.
    past = datetime.now(tz=UTC) - timedelta(seconds=120)
    with SessionLocal() as db:
        with db.begin():
            r = db.get(AuditOutboxRecord, record_id)
            assert r is not None
            r.status = "claimed"
            r.claimed_until = past
            r.attempt_count = 1

    with SessionLocal() as db:
        with db.begin():
            reclaimed = claim_pending_batch(db, limit=1)

    assert len(reclaimed) == 1
    assert reclaimed[0].attempt_count == 2


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def test_mark_delivered_sets_status_and_timestamp() -> None:
    record = _enqueue_one()
    record_id = record.id

    with SessionLocal() as db:
        with db.begin():
            [r] = claim_pending_batch(db, limit=1)
            mark_delivered(db, r)

    with SessionLocal() as db:
        reloaded = db.get(AuditOutboxRecord, record_id)
    assert reloaded is not None
    assert reloaded.status == "delivered"
    assert reloaded.delivered_at is not None
    assert reloaded.claimed_until is None


def test_delivered_record_not_re_claimed() -> None:
    _enqueue_one()

    with SessionLocal() as db:
        with db.begin():
            [r] = claim_pending_batch(db, limit=1)
            mark_delivered(db, r)

    with SessionLocal() as db:
        with db.begin():
            second_batch = claim_pending_batch(db, limit=1)

    assert len(second_batch) == 0


def test_idempotency_key_stable_across_retries() -> None:
    """The idempotency_key on a released-and-reclaimed record does not change."""
    record = _enqueue_one()
    original_key = record.idempotency_key
    record_id = record.id

    # Claim and release twice.
    for _ in range(2):
        with SessionLocal() as db:
            with db.begin():
                [r] = claim_pending_batch(db, limit=1)
                release_claim(db, r)

    with SessionLocal() as db:
        reloaded = db.get(AuditOutboxRecord, record_id)
    assert reloaded is not None
    assert reloaded.idempotency_key == original_key


# ---------------------------------------------------------------------------
# Release claim
# ---------------------------------------------------------------------------


def test_release_claim_returns_record_to_pending() -> None:
    record = _enqueue_one()
    record_id = record.id

    with SessionLocal() as db:
        with db.begin():
            [r] = claim_pending_batch(db, limit=1)
            release_claim(db, r)

    with SessionLocal() as db:
        reloaded = db.get(AuditOutboxRecord, record_id)
    assert reloaded is not None
    assert reloaded.status == "pending"
    assert reloaded.claimed_until is None


# ---------------------------------------------------------------------------
# deliver_pending_events
# ---------------------------------------------------------------------------


def test_deliver_pending_events_no_delivery_fn_retains_pending() -> None:
    """With no delivery function, records remain pending (released after claim)."""
    _enqueue_one()

    result = deliver_pending_events(delivery_fn=None)

    assert result["claimed"] == 1
    assert result["delivered"] == 0
    assert result["released"] == 1
    assert pending_count() == 1


def test_deliver_pending_events_success_marks_delivered() -> None:
    _enqueue_one()
    delivered_payloads: list[dict] = []

    result = deliver_pending_events(delivery_fn=delivered_payloads.append)

    assert result["delivered"] == 1
    assert result["released"] == 0
    assert len(delivered_payloads) == 1
    assert delivered_payloads[0]["event_type"] == "test.event"
    assert pending_count() == 0


def test_deliver_pending_events_failure_releases_for_retry() -> None:
    _enqueue_one()

    def _fail(payload):
        raise RuntimeError("simulated delivery failure")

    result = deliver_pending_events(delivery_fn=_fail)

    assert result["delivered"] == 0
    assert result["released"] == 1
    assert pending_count() == 1


def test_deliver_pending_events_payload_contains_idempotency_key() -> None:
    record = _enqueue_one(event_type="test.payload")
    payloads: list[dict] = []

    deliver_pending_events(delivery_fn=payloads.append)

    assert len(payloads) == 1
    assert payloads[0]["idempotency_key"] == record.idempotency_key


def test_deliver_pending_events_payload_does_not_contain_private_key() -> None:
    """Delivery payload must not leak key material (checked by field absence)."""
    _enqueue_one(description="normal description without key material")
    payloads: list[dict] = []

    deliver_pending_events(delivery_fn=payloads.append)

    assert len(payloads) == 1
    keys = set(payloads[0].keys())

    # Extended schema fields that are safe to deliver externally.
    expected = {
        "schema_version",
        "service",
        "idempotency_key",
        "event_id",
        "event_type",
        "severity",
        "client_id",
        "update_id",
        "description",
        "attempt_count",
        "created_at",
    }
    assert keys == expected, (
        f"Unexpected payload fields: {keys - expected}; missing: {expected - keys}"
    )

    # Private-key material must never appear — check by exact field names.
    # Use specific banned names rather than substring patterns so that
    # legitimate fields like "idempotency_key" do not trigger false positives.
    banned_fields = {
        "private_key", "public_key", "signing_key", "secret", "token",
        "password", "api_key", "auth_key", "hmac_key", "encryption_key",
    }
    overlap = keys & banned_fields
    assert not overlap, f"Payload contains banned field(s): {overlap}"


def test_deliver_pending_events_multiple_records() -> None:
    for i in range(3):
        _enqueue_one(update_id=f"update-{i}")

    payloads: list[dict] = []
    result = deliver_pending_events(delivery_fn=payloads.append, max_events=10)

    assert result["delivered"] == 3
    assert len(payloads) == 3
    assert pending_count() == 0


# ---------------------------------------------------------------------------
# Restart-equivalent persistence
# ---------------------------------------------------------------------------


def test_outbox_record_persists_across_session_boundaries() -> None:
    """Enqueued records survive a new SessionLocal() call (StaticPool reuse)."""
    record = _enqueue_one(event_type="test.persist")
    record_id = record.id

    # Read in a fresh session.
    with SessionLocal() as db2:
        reloaded = db2.get(AuditOutboxRecord, record_id)

    assert reloaded is not None
    assert reloaded.event_type == "test.persist"
    assert reloaded.status == "pending"


# ---------------------------------------------------------------------------
# audit/service.record_audit_event: atomic outbox enqueue
# ---------------------------------------------------------------------------


def test_record_audit_event_creates_outbox_record() -> None:
    record_audit_event(
        event_type="security.test_outbox",
        severity="info",
        description="test",
        client_id="c-outbox",
        update_id="u-outbox",
    )

    assert pending_count() == 1


def test_record_audit_event_outbox_has_correct_fields() -> None:
    record_audit_event(
        event_type="security.field_check",
        severity="high",
        description="field check desc",
        client_id="c-field",
        update_id="u-field",
    )

    with SessionLocal() as db:
        outbox_record = db.scalar(
            select(AuditOutboxRecord).where(
                AuditOutboxRecord.event_type == "security.field_check"
            )
        )

    assert outbox_record is not None
    assert outbox_record.severity == "high"
    assert outbox_record.client_id == "c-field"
    assert outbox_record.update_id == "u-field"
    assert outbox_record.event_id is not None  # FK linked to audit_events row


# ---------------------------------------------------------------------------
# enforcement/approval_service._transition: atomic outbox enqueue
# ---------------------------------------------------------------------------


def _register_update_for_transition(
    update_id: str = "trans-upd-001",
    client_id: str = "trans-client",
) -> None:
    register_validated_update(
        update_id=update_id,
        client_id=client_id,
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=10, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256="a" * 64,
        risk_score=10,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=["none"],
        detector_version="v1",
        detector_config={"threshold": 0.5},
    )
    record_ingestion_audit_result(
        client_id=client_id,
        update_id=update_id,
        audit_status="persisted",
        audit_failures=(),
    )


def test_transition_enqueues_outbox_record() -> None:
    """approve_update (via _transition) must add an outbox record atomically."""
    _clear_approvals()
    _register_update_for_transition()

    # Must have no outbox records before the transition.
    assert pending_count() == 0

    approve_update(
        client_id="trans-client",
        update_id="trans-upd-001",
        reason="test approval",
    )

    # The outbox record from _transition() must now be pending.
    assert pending_count() >= 1


# ---------------------------------------------------------------------------
# Bounded retries and dead-letter handling
# ---------------------------------------------------------------------------


def test_release_claim_with_backoff_sets_retry_after() -> None:
    """After a failed delivery, retry_after is set to a future time."""
    record = _enqueue_one()
    record_id = record.id

    with SessionLocal() as db:
        with db.begin():
            [r] = claim_pending_batch(db, limit=1)
            release_claim_with_backoff(db, r)

    with SessionLocal() as db:
        reloaded = db.get(AuditOutboxRecord, record_id)

    assert reloaded is not None
    assert reloaded.status == "pending"
    assert reloaded.retry_after is not None
    assert reloaded.claimed_until is None


def test_backoff_delays_reclaim() -> None:
    """A pending record with retry_after in the future must not be claimed."""
    record = _enqueue_one()
    record_id = record.id

    # Set retry_after far in the future.
    future = datetime.now(tz=UTC) + timedelta(hours=1)
    with SessionLocal() as db:
        with db.begin():
            r = db.get(AuditOutboxRecord, record_id)
            assert r is not None
            r.retry_after = future

    with SessionLocal() as db:
        with db.begin():
            batch = claim_pending_batch(db, limit=10)

    assert len(batch) == 0, "Record with future retry_after must not be claimable"


def test_expired_retry_after_allows_reclaim() -> None:
    """A pending record whose retry_after is in the past is claimable."""
    record = _enqueue_one()
    record_id = record.id

    past = datetime.now(tz=UTC) - timedelta(seconds=120)
    with SessionLocal() as db:
        with db.begin():
            r = db.get(AuditOutboxRecord, record_id)
            assert r is not None
            r.retry_after = past

    with SessionLocal() as db:
        with db.begin():
            batch = claim_pending_batch(db, limit=10)

    assert len(batch) == 1


def test_bounded_retries_moves_to_dead_letter() -> None:
    """After MAX_DELIVERY_ATTEMPTS the record is moved to dead_letter."""
    record = _enqueue_one()
    record_id = record.id

    # Pre-set attempt_count to one below the limit so a single failure tips it over.
    with SessionLocal() as db:
        with db.begin():
            r = db.get(AuditOutboxRecord, record_id)
            assert r is not None
            r.attempt_count = MAX_DELIVERY_ATTEMPTS - 1
            r.retry_after = None

    def _fail(payload):
        raise RuntimeError("simulated delivery failure")

    result = deliver_pending_events(
        delivery_fn=_fail,
        max_attempts=MAX_DELIVERY_ATTEMPTS,
    )

    with SessionLocal() as db:
        reloaded = db.get(AuditOutboxRecord, record_id)

    assert reloaded is not None
    assert reloaded.status == "dead_letter", (
        f"Expected dead_letter after {MAX_DELIVERY_ATTEMPTS} attempts, got {reloaded.status!r}"
    )
    assert result["dead_lettered"] == 1
    assert result["released"] == 0
    assert pending_count() == 0
    assert dead_letter_count() == 1


def test_dead_letter_records_not_re_claimed() -> None:
    """Dead-lettered records must not appear in claim_pending_batch."""
    record = _enqueue_one()
    record_id = record.id

    with SessionLocal() as db:
        with db.begin():
            r = db.get(AuditOutboxRecord, record_id)
            assert r is not None
            r.status = "dead_letter"

    with SessionLocal() as db:
        with db.begin():
            batch = claim_pending_batch(db, limit=10)

    assert len(batch) == 0
    assert dead_letter_count() == 1


def test_no_delivery_fn_does_not_dead_letter() -> None:
    """With no delivery_fn, records are released with no backoff and never dead-lettered."""
    record = _enqueue_one()
    record_id = record.id

    # Pre-set attempt_count beyond max — still should not dead-letter when delivery_fn=None.
    with SessionLocal() as db:
        with db.begin():
            r = db.get(AuditOutboxRecord, record_id)
            assert r is not None
            r.attempt_count = MAX_DELIVERY_ATTEMPTS

    result = deliver_pending_events(delivery_fn=None)

    with SessionLocal() as db:
        reloaded = db.get(AuditOutboxRecord, record_id)

    assert reloaded is not None
    assert reloaded.status == "pending"
    assert reloaded.retry_after is None
    assert result["dead_lettered"] == 0
    assert dead_letter_count() == 0


def test_deliver_pending_events_includes_dead_lettered_key() -> None:
    """The result dict always includes the dead_lettered key."""
    result = deliver_pending_events(delivery_fn=None)
    assert "dead_lettered" in result


def test_restart_equivalent_via_expired_claim() -> None:
    """A claimed record with an expired claim (simulated worker crash) is reclaimable."""
    record = _enqueue_one()
    record_id = record.id

    # Simulate worker crash: status=claimed, claimed_until in the past.
    past = datetime.now(tz=UTC) - timedelta(seconds=600)
    with SessionLocal() as db:
        with db.begin():
            r = db.get(AuditOutboxRecord, record_id)
            assert r is not None
            r.status = "claimed"
            r.claimed_until = past
            r.attempt_count = 2
            r.retry_after = None

    # Another worker (simulated restart) must be able to reclaim it.
    with SessionLocal() as db:
        with db.begin():
            reclaimed = claim_pending_batch(db, limit=10)

    assert len(reclaimed) == 1
    assert reclaimed[0].attempt_count == 3


def test_duplicate_idempotency_key_rejected() -> None:
    """Two outbox records with the same idempotency_key cannot coexist."""
    with SessionLocal() as db:
        with db.begin():
            r1 = enqueue(
                db,
                event_id=None,
                event_type="test.dup",
                severity="info",
                description="first",
                client_id=None,
                update_id=None,
            )
            db.flush()
            # Manually set idempotency_key so we control the collision.
            r1.idempotency_key = "fixed-key-12345"

    import sqlalchemy.exc

    with pytest.raises((sqlalchemy.exc.IntegrityError, Exception)):
        with SessionLocal() as db:
            with db.begin():
                r2 = enqueue(
                    db,
                    event_id=None,
                    event_type="test.dup2",
                    severity="info",
                    description="second",
                    client_id=None,
                    update_id=None,
                )
                db.flush()
                r2.idempotency_key = "fixed-key-12345"


def test_transition_rollback_removes_outbox_record(monkeypatch) -> None:
    """If AuditEvent construction fails, the outbox record is also rolled back."""
    _clear_approvals()
    _register_update_for_transition(update_id="trans-upd-002", client_id="trans-client")

    import enforcement.approval_service as _svc

    def _raise_on_enqueue(*args, **kwargs):
        raise RuntimeError("simulated enqueue failure")

    monkeypatch.setattr(_svc, "_enqueue_outbox", _raise_on_enqueue)

    with pytest.raises(RuntimeError, match="simulated enqueue failure"):
        approve_update(
            client_id="trans-client",
            update_id="trans-upd-002",
            reason="rollback test",
        )

    # Neither the state transition audit event nor the outbox record should exist.
    assert pending_count() == 0
