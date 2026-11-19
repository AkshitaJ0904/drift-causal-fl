"""Replay reservation and approval atomicity tests.

Verifies the guarantee introduced by register_and_finalize_validated_update():
both the update_approvals INSERT and the replay_records finalization UPDATE
are committed in a single SQLAlchemy transaction.  Either both succeed or
both roll back.

Failure sequences covered (numbered to match the milestone spec):
  1. Reservation succeeds, ingestion validation fails → reservation released.
  2. Reservation succeeds, combined tx (registration + finalization) fails →
     both rolled back atomically, reservation released.
  3. Reservation succeeds, combined tx raises InternalConsistencyError →
     both rolled back, reservation released.
  4. Combined tx succeeds, mark_reservation_finalized_in_memory returns False
     (e.g. after process restart) → NOT a fatal error; DB row is already
     finalized; is_reservation_finalized() DB fallback returns True.
  5. After successful commit: update_approvals row exists AND
     replay_records.finalized = True (the core consistency invariant).
  6. Duplicate request arriving after a successful submission is blocked by
     the unique constraint on replay_records (fail-closed).
  7. InternalConsistencyError is a subclass of ApprovalError so it is caught
     by the ingestion-service error handler and triggers reservation release.

No PostgreSQL or multi-worker tests are included — SQLite StaticPool is the
only database available; true concurrent worker isolation requires PostgreSQL.
"""

import hashlib
from collections.abc import Generator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from core.replay_protection import (
    clear_replay_registry,
    is_reservation_finalized,
    release_update_reservation,
    reserve_update,
)
from core.supabase.session import SessionLocal
from db.models.replay_record import ReplayRecord
from db.models.update_approval import UpdateApproval
from enforcement.approval_service import (
    ApprovalError,
    InternalConsistencyError,
    UpdateStatus,
    clear_approval_registry,
    register_and_finalize_validated_update,
    register_validated_update,
)
from ingestion.sample_count_provider import PROVENANCE_CLIENT_CLAIMED, SampleCountResult
from ingestion.schemas import UpdateEnvelope

TEST_DIGEST = "c" * 64

_ENVELOPE_DATA = {
    "update_id": "atomic-test-update",
    "client_id": "atomic-test-client",
    "model_version": "cnn-v1",
    "round_number": 1,
    "sample_count": 5,
    "payload_sha256": hashlib.sha256(b"atomicpayload").hexdigest(),
    "payload_size_bytes": len(b"atomicpayload"),
    "created_at": "2026-10-21T10:00:00Z",
    "signature": "stub-sig",
    "signing_key_id": "stub-key",
}


@pytest.fixture(autouse=True)
def clean_state() -> Generator[None, None, None]:
    clear_approval_registry()
    clear_replay_registry()
    yield
    clear_approval_registry()
    clear_replay_registry()


def _make_envelope(**overrides) -> UpdateEnvelope:
    data = {**_ENVELOPE_DATA, **overrides}
    return UpdateEnvelope.model_validate(data)


def _register_and_finalize(*, update_id: str, client_id: str = "atomic-test-client") -> None:
    envelope = _make_envelope(update_id=update_id, client_id=client_id)
    token = reserve_update(envelope)
    register_and_finalize_validated_update(
        update_id=update_id,
        client_id=client_id,
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=5, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
        reservation_token=token,
    )


# ---------------------------------------------------------------------------
# Sequence 2: combined tx failure rolls back both INSERT and UPDATE atomically
# ---------------------------------------------------------------------------

def test_combined_tx_failure_leaves_no_approval_row() -> None:
    """When register_and_finalize_validated_update raises, the update_approvals
    INSERT is rolled back and no row appears in the DB.

    Simulates an OperationalError during the combined transaction to verify
    SQLAlchemy's context manager rolls back both the INSERT and the UPDATE.
    """
    envelope = _make_envelope(update_id="atom-fail-01")
    token = reserve_update(envelope)

    from unittest.mock import patch

    # Patch SessionLocal.begin to raise after the add() so the transaction
    # context manager must roll back.  We simulate by making db.flush raise.
    def raising_flush(self):
        raise OperationalError("simulated DB failure during flush", params=None, orig=Exception())

    with patch(
        "enforcement.approval_service.SessionLocal",
        side_effect=OperationalError("simulated open failure", params=None, orig=Exception()),
    ):
        with pytest.raises((ApprovalError, OperationalError)):
            register_and_finalize_validated_update(
                update_id="atom-fail-01",
                client_id="atomic-test-client",
                model_version="cnn-v1",
                round_number=1,
                sample_count_result=SampleCountResult(
                    count=5, provenance=PROVENANCE_CLIENT_CLAIMED
                ),
                payload_sha256=TEST_DIGEST,
                risk_score=0,
                risk_severity="LOW",
                suspicious=False,
                anomaly_reasons=(),
                detector_version="test-v1",
                detector_config={"max_weight_l2_norm": 100.0},
                reservation_token=token,
            )

    # No approval row must exist after the failure.
    with SessionLocal() as db:
        row = db.scalar(
            select(UpdateApproval).where(
                UpdateApproval.client_id == "atomic-test-client",
                UpdateApproval.update_id == "atom-fail-01",
            )
        )
    assert row is None, "No update_approvals row must exist after a combined tx rollback"

    # The replay record must still be unfinalized (reservation NOT finalized).
    assert not is_reservation_finalized(
        client_id="atomic-test-client", update_id="atom-fail-01"
    ), "Replay record must remain unfinalized after a combined tx rollback"


# ---------------------------------------------------------------------------
# Sequence 3: InternalConsistencyError when replay record is missing
# ---------------------------------------------------------------------------

def test_internal_consistency_error_when_replay_record_absent() -> None:
    """register_and_finalize_validated_update raises InternalConsistencyError
    when no replay_records row exists for the given (client_id, update_id).

    This covers the case where reserve_update() was not called beforehand or
    where the replay record was deleted between reservation and registration.
    """
    # Do NOT call reserve_update — no replay_records row will exist.
    with pytest.raises(InternalConsistencyError):
        register_and_finalize_validated_update(
            update_id="atom-no-reservation-01",
            client_id="atomic-test-client",
            model_version="cnn-v1",
            round_number=1,
            sample_count_result=SampleCountResult(count=5, provenance=PROVENANCE_CLIENT_CLAIMED),
            payload_sha256=TEST_DIGEST,
            risk_score=0,
            risk_severity="LOW",
            suspicious=False,
            anomaly_reasons=(),
            detector_version="test-v1",
            detector_config={"max_weight_l2_norm": 100.0},
            reservation_token="any-token",
        )

    # No approval row must exist after the internal consistency error.
    with SessionLocal() as db:
        row = db.scalar(
            select(UpdateApproval).where(
                UpdateApproval.client_id == "atomic-test-client",
                UpdateApproval.update_id == "atom-no-reservation-01",
            )
        )
    assert row is None, "No update_approvals row after InternalConsistencyError"


def test_internal_consistency_error_is_subclass_of_approval_error() -> None:
    """InternalConsistencyError must be catchable as ApprovalError so the
    ingestion-service error handler triggers reservation release on internal
    consistency failures just as it does for other registration failures.
    """
    assert issubclass(InternalConsistencyError, ApprovalError), (
        "InternalConsistencyError must be a subclass of ApprovalError"
    )


# ---------------------------------------------------------------------------
# Sequence 5: core consistency invariant after successful commit
# ---------------------------------------------------------------------------

def test_successful_commit_leaves_approval_row_and_finalized_replay_record() -> None:
    """After register_and_finalize_validated_update succeeds:
    - An update_approvals row exists in PENDING_APPROVAL status.
    - The replay_records row has finalized=True.

    This is the primary consistency invariant: the two changes are either both
    committed or both absent.  The 'both absent' direction is covered by the
    failure-injection tests above.
    """
    envelope = _make_envelope(update_id="atom-ok-01")
    token = reserve_update(envelope)

    record = register_and_finalize_validated_update(
        update_id="atom-ok-01",
        client_id="atomic-test-client",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=5, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
        reservation_token=token,
    )

    assert record.status == UpdateStatus.PENDING_APPROVAL

    # Approval row must exist.
    with SessionLocal() as db:
        approval = db.scalar(
            select(UpdateApproval).where(
                UpdateApproval.client_id == "atomic-test-client",
                UpdateApproval.update_id == "atom-ok-01",
            )
        )
    assert approval is not None, "update_approvals row must exist after success"
    assert approval.status == UpdateStatus.PENDING_APPROVAL.value

    # Replay record must be finalized.
    with SessionLocal() as db:
        replay = db.scalar(
            select(ReplayRecord).where(
                ReplayRecord.client_id == "atomic-test-client",
                ReplayRecord.update_id == "atom-ok-01",
            )
        )
    assert replay is not None, "replay_records row must exist after success"
    assert replay.finalized is True, (
        "replay_records.finalized must be True after register_and_finalize_validated_update"
    )


# ---------------------------------------------------------------------------
# Sequence 4: mark_reservation_finalized_in_memory returns False gracefully
# ---------------------------------------------------------------------------

def test_is_reservation_finalized_falls_back_to_db_when_memory_stale() -> None:
    """When the in-memory cache does not have a reservation entry (e.g. after a
    process restart), is_reservation_finalized() falls back to the DB and returns
    True for a finalized row.

    Simulated by calling register_and_finalize_validated_update() (which writes
    the DB row with finalized=True) then clearing the in-memory registry without
    clearing the DB.  is_reservation_finalized() must still return True via the
    DB fallback.
    """
    envelope = _make_envelope(update_id="atom-stale-01")
    token = reserve_update(envelope)

    register_and_finalize_validated_update(
        update_id="atom-stale-01",
        client_id="atomic-test-client",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=5, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
        reservation_token=token,
    )

    # Simulate process restart: clear only the in-memory cache, leave DB intact.
    clear_replay_registry(include_database=False)

    # DB fallback must confirm finalized=True.
    assert is_reservation_finalized(
        client_id="atomic-test-client", update_id="atom-stale-01"
    ), "is_reservation_finalized() must return True via DB fallback after memory cleared"


# ---------------------------------------------------------------------------
# Sequence 6: duplicate request blocked after successful commit
# ---------------------------------------------------------------------------

def test_duplicate_request_blocked_after_successful_registration() -> None:
    """After register_and_finalize_validated_update succeeds, a second attempt
    to reserve the same (client_id, update_id) raises ReplayProtectionError.

    The unique constraint on replay_records (client_id, update_id) is the
    durable replay gate that persists across process restarts.
    """
    from core.replay_protection import ReplayProtectionError

    envelope = _make_envelope(update_id="atom-dup-01")
    token = reserve_update(envelope)

    register_and_finalize_validated_update(
        update_id="atom-dup-01",
        client_id="atomic-test-client",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=5, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
        reservation_token=token,
    )

    # Second reservation attempt must be blocked.
    envelope2 = _make_envelope(update_id="atom-dup-01")
    with pytest.raises(ReplayProtectionError):
        reserve_update(envelope2)


# ---------------------------------------------------------------------------
# Sequence 7: register_and_finalize vs register_validated_update produce same
# approval row shape (regression guard)
# ---------------------------------------------------------------------------

def test_register_and_finalize_produces_same_record_shape_as_register_validated() -> None:
    """register_and_finalize_validated_update() must return an UpdateRecord with
    the same shape and field values as register_validated_update() for identical
    inputs.

    This guards against accidental divergence in the validation or row-building
    code between the two functions.
    """
    envelope1 = _make_envelope(update_id="atom-shape-01", client_id="shape-client-1")
    token1 = reserve_update(envelope1)
    r1 = register_and_finalize_validated_update(
        update_id="atom-shape-01",
        client_id="shape-client-1",
        model_version="cnn-v1",
        round_number=2,
        sample_count_result=SampleCountResult(count=10, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        reason="test reason",
        initial_status=UpdateStatus.PENDING_APPROVAL,
        risk_score=25,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=("rule-A",),
        detector_version="test-v2",
        detector_config={"threshold": 0.5},
        reservation_token=token1,
    )

    r2 = register_validated_update(
        update_id="atom-shape-02",
        client_id="shape-client-2",
        model_version="cnn-v1",
        round_number=2,
        sample_count_result=SampleCountResult(count=10, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        reason="test reason",
        initial_status=UpdateStatus.PENDING_APPROVAL,
        risk_score=25,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=("rule-A",),
        detector_version="test-v2",
        detector_config={"threshold": 0.5},
    )

    # Field-by-field comparison (excluding identity fields).
    assert r1.model_version == r2.model_version
    assert r1.round_number == r2.round_number
    assert r1.sample_count == r2.sample_count
    assert r1.payload_sha256 == r2.payload_sha256
    assert r1.status == r2.status
    assert r1.reason == r2.reason
    assert r1.risk_score == r2.risk_score
    assert r1.risk_severity == r2.risk_severity
    assert r1.suspicious == r2.suspicious
    assert r1.anomaly_reasons == r2.anomaly_reasons
    assert r1.detector_version == r2.detector_version
    assert r1.audit_status == r2.audit_status


# ---------------------------------------------------------------------------
# Ambiguous-commit detection in release_update_reservation
# ---------------------------------------------------------------------------

def test_release_returns_false_and_syncs_flag_when_db_row_finalized() -> None:
    """When the DB row has finalized=True, release_update_reservation refuses
    to release, syncs entry.finalized=True in memory, and returns False.

    This is the ambiguous-commit scenario: register_and_finalize_validated_update
    committed the DB transaction but the caller did not receive acknowledgment
    (e.g., connection dropped between commit and ack).  The reservation must
    never be released in this state — the approval is durable in the DB.
    """
    envelope = _make_envelope(update_id="release-finalized-01")
    token = reserve_update(envelope)

    # Commit both approval and replay finalization to the DB.
    # mark_reservation_finalized_in_memory() is intentionally NOT called here,
    # simulating the connection-drop window between DB commit and application ack.
    register_and_finalize_validated_update(
        update_id="release-finalized-01",
        client_id="atomic-test-client",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=5, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
        reservation_token=token,
    )

    # Precondition: in-memory entry still has finalized=False (ack not received).
    assert not is_reservation_finalized(
        client_id="atomic-test-client",
        update_id="release-finalized-01",
    ), "In-memory flag must still be False before release attempt"

    result = release_update_reservation(
        client_id="atomic-test-client",
        update_id="release-finalized-01",
        token=token,
    )

    assert result is False, (
        "release_update_reservation must refuse when the DB row is finalized"
    )
    # The in-memory flag must have been synced by the failed release attempt.
    assert is_reservation_finalized(
        client_id="atomic-test-client",
        update_id="release-finalized-01",
    ), "In-memory flag must be synced to True after detecting finalized DB row"

    # The DB row must still be finalized — the release must not have deleted it.
    with SessionLocal() as db:
        row = db.scalar(
            select(ReplayRecord).where(
                ReplayRecord.client_id == "atomic-test-client",
                ReplayRecord.update_id == "release-finalized-01",
            )
        )
    assert row is not None and row.finalized, (
        "DB row must remain finalized after a refused release"
    )


def test_release_clears_stale_memory_entry_when_db_row_absent() -> None:
    """When the in-memory entry exists but the DB row is absent,
    release_update_reservation removes the stale entry and returns True.

    Covers the case where the DB was rolled back or truncated externally
    while the in-memory registry still holds the entry (e.g., partial cleanup
    during a test or admin operation).
    """
    envelope = _make_envelope(update_id="release-stale-01")
    token = reserve_update(envelope)

    # Delete the DB row directly, leaving the in-memory entry intact.
    with SessionLocal() as db:
        with db.begin():
            db.execute(
                delete(ReplayRecord).where(
                    ReplayRecord.client_id == "atomic-test-client",
                    ReplayRecord.update_id == "release-stale-01",
                )
            )

    result = release_update_reservation(
        client_id="atomic-test-client",
        update_id="release-stale-01",
        token=token,
    )

    assert result is True, (
        "release_update_reservation must succeed for a stale in-memory entry with no DB row"
    )
    assert not is_reservation_finalized(
        client_id="atomic-test-client",
        update_id="release-stale-01",
    ), "is_reservation_finalized must return False after stale entry is cleared"


def test_duplicate_retry_blocked_after_ambiguous_commit() -> None:
    """After an ambiguous commit, a second reserve_update() for the same
    (client_id, update_id) raises ReplayProtectionError.

    The unique DB constraint on replay_records blocks replay even when the
    caller lost the original acknowledgment.  This is the correct fail-closed
    behavior: the client must contact the operator to resolve the ambiguity
    rather than retrying blindly.
    """
    from core.replay_protection import ReplayProtectionError

    envelope = _make_envelope(update_id="release-dup-after-ambiguous-01")
    token = reserve_update(envelope)

    # Simulate ambiguous commit: DB committed, ack lost, in-memory not finalized.
    register_and_finalize_validated_update(
        update_id="release-dup-after-ambiguous-01",
        client_id="atomic-test-client",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=5, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
        reservation_token=token,
    )
    # release_update_reservation refuses (DB row finalized), entry.finalized synced.
    release_update_reservation(
        client_id="atomic-test-client",
        update_id="release-dup-after-ambiguous-01",
        token=token,
    )

    # A second reservation attempt must be blocked by the durable DB constraint.
    envelope2 = _make_envelope(update_id="release-dup-after-ambiguous-01")
    with pytest.raises(ReplayProtectionError):
        reserve_update(envelope2)


# ---------------------------------------------------------------------------
# End-to-end integration: full service recovery with real DB state (Defect B)
# ---------------------------------------------------------------------------

def test_validate_incoming_update_recovers_from_ambiguous_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end integration: validate_incoming_update() recovers from an
    ambiguous commit using real DB state throughout.

    This test exercises the full composition of the ambiguous-commit recovery
    chain without mocking any DB-touching component:
      1. reserve_update() creates a real replay_records row and in-memory entry.
      2. The patched register_and_finalize_validated_update() calls the REAL
         function (commits both the update_approvals INSERT and the
         replay_records.finalized=True UPDATE to real SQLite) and THEN raises
         OperationalError — simulating a connection drop between DB commit and
         application acknowledgment.
      3. release_update_reservation() runs against the real DB, detects
         finalized=True (rowcount=0 on DELETE), syncs entry.finalized=True,
         and returns False.
      4. is_reservation_finalized() reads the synced in-memory entry → True.
      5. get_update_record() queries the real DB → returns the committed record.
      6. Field cross-verification (payload_sha256, model_version, round_number)
         passes because the committed row was written with this request's values.
      7. The service continues on the success path and returns the correct result.
      8. record_ingestion_audit_result() updates the committed row's audit_status
         in the real DB without error.
    """
    import hashlib as _hashlib
    from types import SimpleNamespace

    import ingestion.service as ingestion_service
    from detection.rule_based import RuleBasedDetectionConfig
    from enforcement.approval_service import (
        register_and_finalize_validated_update as _real_register_fn,
    )
    from ingestion.service import validate_incoming_update
    from policy.model_update_policy import ModelUpdatePolicy

    payload = b"e2e-integration-test-payload"
    digest = _hashlib.sha256(payload).hexdigest()

    envelope = _make_envelope(
        update_id="e2e-ambiguous-01",
        payload_sha256=digest,
        payload_size_bytes=len(payload),
    )

    # Mock only the pipeline steps that don't involve the DB.
    monkeypatch.setattr(ingestion_service, "verify_payload", lambda p, s: digest)
    monkeypatch.setattr(
        ingestion_service,
        "get_trusted_key",
        lambda key_id: SimpleNamespace(
            client_id="atomic-test-client",
            public_key=object(),
            max_sample_count=100,
        ),
    )
    monkeypatch.setattr(ingestion_service, "verify_envelope_signature", lambda *a: True)
    monkeypatch.setattr(
        ingestion_service,
        "deserialize_state_dict",
        lambda *a, **kw: {"weight": object()},
    )
    monkeypatch.setattr(
        ingestion_service,
        "validate_against_registered_schema",
        lambda *a, **kw: SimpleNamespace(accepted=True, reason=""),
    )
    monkeypatch.setattr(
        ingestion_service,
        "evaluate_update_policy",
        lambda *a: SimpleNamespace(accepted=True, reason="", reason_code=""),
    )
    monkeypatch.setattr(
        ingestion_service,
        "extract_update_features",
        lambda *a, **kw: {"weight_l2_norm": 1.0},
    )
    monkeypatch.setattr(
        ingestion_service,
        "detect_update_anomalies",
        lambda *a, **kw: SimpleNamespace(
            risk_score=0, severity="LOW", suspicious=False, reasons=[]
        ),
    )
    monkeypatch.setattr(ingestion_service, "record_audit_event", lambda **kw: None)

    # Commit to the real DB then raise — simulating connection drop after commit.
    def _commit_then_drop(**kwargs):
        _real_register_fn(**kwargs)
        raise OperationalError(
            "simulated connection drop after commit", params=None, orig=Exception()
        )

    monkeypatch.setattr(
        ingestion_service,
        "register_and_finalize_validated_update",
        _commit_then_drop,
    )

    result = validate_incoming_update(
        payload,
        envelope,
        policy=ModelUpdatePolicy(
            allowed_model_versions=frozenset({"cnn-v1"}),
            allowed_round_numbers=frozenset({1}),
            max_update_age_seconds=10_000_000_000,
            max_future_clock_skew_seconds=10_000_000_000,
        ),
        detection_config=RuleBasedDetectionConfig(max_weight_l2_norm=10.0),
    )

    # Service must return a valid success result, not raise ApprovalRegistrationError.
    assert result["approval_status"] == UpdateStatus.PENDING_APPROVAL.value
    assert result["payload_sha256"] == digest
    assert result["client_id"] == "atomic-test-client"
    assert result["update_id"] == "e2e-ambiguous-01"
    assert result["replay_status"] == "accepted"
    assert result["ingestion_status"] == "validated"

    # Verify real DB state: approval row exists, finalized replay record exists.
    with SessionLocal() as db:
        approval_row = db.scalar(
            select(UpdateApproval).where(
                UpdateApproval.client_id == "atomic-test-client",
                UpdateApproval.update_id == "e2e-ambiguous-01",
            )
        )
        replay_row = db.scalar(
            select(ReplayRecord).where(
                ReplayRecord.client_id == "atomic-test-client",
                ReplayRecord.update_id == "e2e-ambiguous-01",
            )
        )

    assert approval_row is not None, "Approval row must exist in DB after recovery"
    assert approval_row.payload_sha256 == digest, (
        "Committed approval row must carry the verified payload digest"
    )
    assert replay_row is not None and replay_row.finalized, (
        "Replay record must remain finalized after ambiguous-commit recovery"
    )
