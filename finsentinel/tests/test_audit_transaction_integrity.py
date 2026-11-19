"""Audit transaction integrity tests for _transition() in approval_service.py.

Verifies:
- AuditEvent INSERT and state UPDATE share the same DB transaction (db.begin()).
- If AuditEvent construction raises inside the transaction, the state UPDATE is
  rolled back — both succeed or both fail.
- Concurrent approval attempts produce exactly one winner and one audit event.
- Concurrent approval + rejection produce no contradictory state.
- Direct service calls (approve/reject/quarantine) each write exactly one audit
  event, with the correct event type and severity.
- A failed transition attempt (already-decided update) writes no extra event.

No HTTP layer is involved — these tests call the service layer directly.
"""
from collections.abc import Generator
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select

from core.supabase.session import SessionLocal
from db.models.audit_event import AuditEvent
from enforcement.approval_service import (
    ApprovalError,
    UpdateStatus,
    approve_update,
    clear_approval_registry,
    get_update_record,
    quarantine_update,
    record_ingestion_audit_result,
    register_validated_update,
    reject_update,
)
from ingestion.sample_count_provider import PROVENANCE_CLIENT_CLAIMED, SampleCountResult

TEST_DIGEST = "b" * 64


def _clear_audit_events() -> None:
    with SessionLocal() as db:
        with db.begin():
            db.execute(delete(AuditEvent))


def _register_pending(*, update_id: str, client_id: str = "c-tx") -> None:
    register_validated_update(
        update_id=update_id,
        client_id=client_id,
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=10, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
    )
    record_ingestion_audit_result(
        client_id=client_id,
        update_id=update_id,
        audit_status="persisted",
        audit_failures=(),
    )


@pytest.fixture(autouse=True)
def reset_state() -> Generator[None, None, None]:
    clear_approval_registry()
    _clear_audit_events()
    yield
    clear_approval_registry()
    _clear_audit_events()


# ---------------------------------------------------------------------------
# Failure-injection: AuditEvent construction failure rolls back state change
# ---------------------------------------------------------------------------

def test_audit_event_construction_failure_rolls_back_state_transition() -> None:
    """When AuditEvent construction raises inside the transaction, the state
    UPDATE is rolled back.  The update must remain in PENDING_APPROVAL.

    This verifies that the state change and the audit INSERT share the same
    db.begin() context: any exception before the transaction commits causes
    SQLAlchemy to call db.rollback(), undoing the UPDATE to update_approvals.
    """
    _register_pending(update_id="u-rollback-01")

    with patch(
        "enforcement.approval_service.AuditEvent",
        side_effect=RuntimeError("Simulated audit storage failure"),
    ):
        with pytest.raises(RuntimeError, match="Simulated audit storage failure"):
            approve_update(
                client_id="c-tx",
                update_id="u-rollback-01",
                reason="Testing rollback on audit failure.",
            )

    record = get_update_record(client_id="c-tx", update_id="u-rollback-01")
    assert record.status == UpdateStatus.PENDING_APPROVAL, (
        f"State must remain PENDING_APPROVAL after rollback, got {record.status!r}"
    )

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == "c-tx",
                AuditEvent.update_id == "u-rollback-01",
            )
        ).all()
    assert events == [], (
        f"No audit events must exist after rollback, found {len(events)}"
    )


def test_rejection_audit_failure_rolls_back_state_transition() -> None:
    """reject_update(): audit failure must roll back the REJECTED state change."""
    _register_pending(update_id="u-rollback-02")

    with patch(
        "enforcement.approval_service.AuditEvent",
        side_effect=RuntimeError("Simulated audit storage failure"),
    ):
        with pytest.raises(RuntimeError):
            reject_update(
                client_id="c-tx",
                update_id="u-rollback-02",
                reason="Testing rejection rollback.",
            )

    record = get_update_record(client_id="c-tx", update_id="u-rollback-02")
    assert record.status == UpdateStatus.PENDING_APPROVAL


def test_quarantine_audit_failure_rolls_back_state_transition() -> None:
    """quarantine_update(): audit failure must roll back the QUARANTINED state change."""
    _register_pending(update_id="u-rollback-03")

    with patch(
        "enforcement.approval_service.AuditEvent",
        side_effect=RuntimeError("Simulated audit storage failure"),
    ):
        with pytest.raises(RuntimeError):
            quarantine_update(
                client_id="c-tx",
                update_id="u-rollback-03",
                reason="Testing quarantine rollback.",
            )

    record = get_update_record(client_id="c-tx", update_id="u-rollback-03")
    assert record.status == UpdateStatus.PENDING_APPROVAL


# ---------------------------------------------------------------------------
# Direct service calls write exactly one audit event each
# ---------------------------------------------------------------------------

def test_approve_update_writes_exactly_one_audit_event() -> None:
    """Direct service-layer approve_update() writes exactly one operator.update_approved
    event with severity='info'."""
    _register_pending(update_id="u-audit-01")
    approve_update(client_id="c-tx", update_id="u-audit-01", reason="direct approve test")

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == "c-tx",
                AuditEvent.update_id == "u-audit-01",
                AuditEvent.event_type == "operator.update_approved",
            )
        ).all()
    assert len(events) == 1
    assert events[0].severity == "info"


def test_reject_update_writes_exactly_one_audit_event() -> None:
    """Direct service-layer reject_update() writes exactly one operator.update_rejected
    event with severity='high'."""
    _register_pending(update_id="u-audit-02")
    reject_update(client_id="c-tx", update_id="u-audit-02", reason="direct reject test")

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == "c-tx",
                AuditEvent.update_id == "u-audit-02",
                AuditEvent.event_type == "operator.update_rejected",
            )
        ).all()
    assert len(events) == 1
    assert events[0].severity == "high"


def test_quarantine_update_writes_exactly_one_audit_event() -> None:
    """Direct service-layer quarantine_update() writes exactly one operator.update_quarantined
    event with severity='high'."""
    _register_pending(update_id="u-audit-03")
    quarantine_update(client_id="c-tx", update_id="u-audit-03", reason="direct quarantine test")

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == "c-tx",
                AuditEvent.update_id == "u-audit-03",
                AuditEvent.event_type == "operator.update_quarantined",
            )
        ).all()
    assert len(events) == 1
    assert events[0].severity == "high"


# ---------------------------------------------------------------------------
# Idempotency: failed transition attempt writes no extra audit event
# ---------------------------------------------------------------------------

def test_failed_second_approval_writes_no_extra_audit_event() -> None:
    """A second approve_update() on an already-approved update raises ApprovalError
    and must not add a duplicate audit event.
    """
    _register_pending(update_id="u-idem-01")
    approve_update(client_id="c-tx", update_id="u-idem-01", reason="first approval")

    with pytest.raises(ApprovalError):
        approve_update(
            client_id="c-tx",
            update_id="u-idem-01",
            reason="second approval attempt",
        )

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == "c-tx",
                AuditEvent.update_id == "u-idem-01",
                AuditEvent.event_type == "operator.update_approved",
            )
        ).all()
    assert len(events) == 1, (
        f"Expected exactly 1 audit event after failed second attempt, got {len(events)}"
    )


def test_failed_rejection_after_approval_writes_no_extra_audit_event() -> None:
    """A reject_update() on an already-approved update raises ApprovalError and
    must not write an operator.update_rejected event.  The original approval event
    must still be exactly one.
    """
    _register_pending(update_id="u-idem-02")
    approve_update(client_id="c-tx", update_id="u-idem-02", reason="approved first")

    with pytest.raises(ApprovalError):
        reject_update(
            client_id="c-tx",
            update_id="u-idem-02",
            reason="trying to reject after approval",
        )

    with SessionLocal() as db:
        rejected_events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == "c-tx",
                AuditEvent.update_id == "u-idem-02",
                AuditEvent.event_type == "operator.update_rejected",
            )
        ).all()
    assert len(rejected_events) == 0, "No rejection event when rejection fails"

    with SessionLocal() as db:
        approved_events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == "c-tx",
                AuditEvent.update_id == "u-idem-02",
                AuditEvent.event_type == "operator.update_approved",
            )
        ).all()
    assert len(approved_events) == 1


# ---------------------------------------------------------------------------
# Concurrency: SQL-level atomicity prevents contradictory decisions
# ---------------------------------------------------------------------------

def test_second_approval_attempt_fails_after_first_commits() -> None:
    """After the first approve_update() commits, a second call on the same update
    sees the committed APPROVED state and raises ApprovalError.

    The WHERE status = 'pending_approval' clause is the database-level
    serialization primitive.  The second call's UPDATE matches zero rows
    (the row is no longer in PENDING_APPROVAL), so rowcount=0, which raises
    ApprovalError.  Crucially, no second audit event is written for the failing
    attempt.

    This is the sequential demonstration of the invariant.  On PostgreSQL with
    concurrent transactions, the second transaction sees the first's committed
    state before its own UPDATE executes, producing the same rowcount=0 outcome.

    Note: SQLite StaticPool serializes all writes through a single connection,
    making truly concurrent threading tests unreliable in this test environment.
    See test_concurrent_approvals_exactly_one_winner_one_audit_event in
    test_aggregation_security.py for the HTTP-layer view of duplicate detection.
    """
    _register_pending(update_id="u-conc-01", client_id="c-conc")

    # First approval commits — the WHERE clause matches, rowcount=1.
    record = approve_update(
        client_id="c-conc",
        update_id="u-conc-01",
        reason="first approval commits",
    )
    assert record.status == UpdateStatus.APPROVED

    # Second approval (the loser in the concurrent scenario) must fail.
    with pytest.raises(ApprovalError):
        approve_update(
            client_id="c-conc",
            update_id="u-conc-01",
            reason="second approval attempt — WHERE clause returns rowcount=0",
        )

    # Final state must still be APPROVED.
    final = get_update_record(client_id="c-conc", update_id="u-conc-01")
    assert final.status == UpdateStatus.APPROVED

    # Exactly one audit event: no duplicate from the failed attempt.
    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == "c-conc",
                AuditEvent.update_id == "u-conc-01",
                AuditEvent.event_type == "operator.update_approved",
            )
        ).all()
    assert len(events) == 1


def test_approval_and_rejection_cannot_both_succeed() -> None:
    """After one decision commits, any subsequent decision on the same update
    raises ApprovalError — no contradictory state is possible.

    The WHERE status = 'pending_approval' clause in the UPDATE is the
    database-level serialization primitive.  Once the first decision commits
    (status changes from PENDING_APPROVAL to APPROVED or REJECTED), the second
    decision's UPDATE matches zero rows (rowcount=0) and ApprovalError is raised.
    No audit event is written for the failed second attempt.

    This is a sequential demonstration of the invariant.  The same WHERE-clause
    protection holds for truly concurrent transactions on PostgreSQL row-level
    locking, where the second transaction sees the committed state of the first
    before attempting its own UPDATE.
    """
    _register_pending(update_id="u-conc-02", client_id="c-conc2")

    # First decision succeeds.
    record = approve_update(
        client_id="c-conc2",
        update_id="u-conc-02",
        reason="first decision: approved",
    )
    assert record.status == UpdateStatus.APPROVED

    # Second decision (the loser in the concurrent scenario) must fail.
    with pytest.raises(ApprovalError):
        reject_update(
            client_id="c-conc2",
            update_id="u-conc-02",
            reason="second decision: attempted rejection after approval",
        )

    final_record = get_update_record(client_id="c-conc2", update_id="u-conc-02")
    assert final_record.status == UpdateStatus.APPROVED, (
        "State must remain APPROVED; rejection must not overwrite a committed decision"
    )

    # Exactly one audit event: the approval.  No rejection event.
    with SessionLocal() as db:
        all_decision_events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == "c-conc2",
                AuditEvent.update_id == "u-conc-02",
                AuditEvent.event_type.in_([
                    "operator.update_approved",
                    "operator.update_rejected",
                ]),
            )
        ).all()
    assert len(all_decision_events) == 1, (
        f"Expected exactly one decision audit event, got {len(all_decision_events)}"
    )
    assert all_decision_events[0].event_type == "operator.update_approved"
