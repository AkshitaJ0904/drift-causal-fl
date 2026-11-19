
"""Tests for the persistent approval lifecycle and payload binding."""

import pytest
from sqlalchemy import select

from core.supabase.session import SessionLocal
from db.models.update_approval import UpdateApproval
from enforcement.approval_service import (
    ApprovalError,
    UpdateStatus,
    approve_update,
    clear_approval_registry,
    get_update_record,
    is_approved,
    list_pending_updates,
    quarantine_update,
    record_ingestion_audit_result,
    register_validated_update,
    reject_update,
)
from ingestion.sample_count_provider import PROVENANCE_CLIENT_CLAIMED, SampleCountResult

TEST_DIGEST = "a" * 64


@pytest.fixture(autouse=True)
def reset_approval_registry():
    """Development/test database cleanup."""
    clear_approval_registry()
    yield
    clear_approval_registry()


def register_update(
    *,
    update_id="update-001",
    client_id="client-001",
    model_version="cnn-v1",
    round_number=1,
    sample_count=1,
    payload_sha256=TEST_DIGEST,
):
    register_validated_update(
        update_id=update_id,
        client_id=client_id,
        model_version=model_version,
        round_number=round_number,
        sample_count_result=SampleCountResult(
            count=sample_count, provenance=PROVENANCE_CLIENT_CLAIMED
        ),
        payload_sha256=payload_sha256,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-detector-v1",
        detector_config={"test_threshold": 1.0},
    )
    record_ingestion_audit_result(
        client_id=client_id,
        update_id=update_id,
        audit_status="persisted",
        audit_failures=(),
    )
    return get_update_record(client_id=client_id, update_id=update_id)


def test_new_update_requires_approval():
    record = register_update()

    assert record.status == UpdateStatus.PENDING_APPROVAL
    assert record.payload_sha256 == TEST_DIGEST
    assert not is_approved(
        client_id="client-001",
        update_id="update-001",
        model_version="cnn-v1",
        round_number=1,
        sample_count=1,
        payload_sha256=TEST_DIGEST,
    )


def test_approval_record_is_persisted_in_database():
    record = register_update()

    with SessionLocal() as db:
        row = db.scalar(
            select(UpdateApproval).where(
                UpdateApproval.client_id == "client-001",
                UpdateApproval.update_id == "update-001",
            )
        )

    assert row is not None
    assert row.status == UpdateStatus.PENDING_APPROVAL.value
    assert row.payload_sha256 == TEST_DIGEST
    assert record.risk_score == 0
    assert record.risk_severity == "LOW"
    assert record.suspicious is False
    assert record.detector_version == "test-detector-v1"
    assert record.detector_config == {"test_threshold": 1.0}
    assert record.audit_status == "persisted"


def test_approved_update_matches_payload_model_and_round():
    register_update()

    approve_update(
        client_id="client-001",
        update_id="update-001",
        reason="Approved by reviewer.",
    )

    assert is_approved(
        client_id="client-001",
        update_id="update-001",
        model_version="cnn-v1",
        round_number=1,
        sample_count=1,
        payload_sha256=TEST_DIGEST,
    )


def test_approval_does_not_apply_to_another_payload():
    register_update()

    approve_update(
        client_id="client-001",
        update_id="update-001",
        reason="Approved by reviewer.",
    )

    assert not is_approved(
        client_id="client-001",
        update_id="update-001",
        model_version="cnn-v1",
        round_number=1,
        sample_count=1,
        payload_sha256="b" * 64,
    )


def test_approval_does_not_apply_to_another_sample_count():
    register_update(sample_count=5)

    approve_update(
        client_id="client-001",
        update_id="update-001",
        reason="Approved by reviewer.",
    )

    assert not is_approved(
        client_id="client-001",
        update_id="update-001",
        model_version="cnn-v1",
        round_number=1,
        sample_count=6,
        payload_sha256=TEST_DIGEST,
    )


def test_approval_does_not_apply_to_another_model_version():
    register_update()

    approve_update(
        client_id="client-001",
        update_id="update-001",
        reason="Approved by reviewer.",
    )

    assert not is_approved(
        client_id="client-001",
        update_id="update-001",
        model_version="cnn-v2",
        round_number=1,
        sample_count=1,
        payload_sha256=TEST_DIGEST,
    )


def test_rejected_update_cannot_be_approved():
    register_update()

    reject_update(
        client_id="client-001",
        update_id="update-001",
        reason="Policy violation.",
    )

    with pytest.raises(ApprovalError):
        approve_update(
            client_id="client-001",
            update_id="update-001",
            reason="Attempt to approve again.",
        )


def test_quarantined_update_cannot_be_approved():
    register_update()

    quarantine_update(
        client_id="client-001",
        update_id="update-001",
        reason="Requires investigation.",
    )

    with pytest.raises(ApprovalError):
        approve_update(
            client_id="client-001",
            update_id="update-001",
            reason="Attempt to approve again.",
        )


def test_unknown_update_is_not_approved():
    assert not is_approved(
        client_id="unknown-client",
        update_id="unknown-update",
        model_version="cnn-v1",
        round_number=1,
        sample_count=1,
        payload_sha256=TEST_DIGEST,
    )


def test_unknown_update_record_raises_error():
    with pytest.raises(ApprovalError, match="Unknown update"):
        get_update_record(
            client_id="unknown-client",
            update_id="unknown-update",
        )


def test_duplicate_registration_is_rejected():
    register_update()

    with pytest.raises(ApprovalError, match="already registered"):
        register_update()


def test_invalid_payload_digest_is_rejected():
    with pytest.raises(ValueError, match="SHA-256"):
        register_update(payload_sha256="not-a-digest")


def test_blank_approval_reason_is_rejected():
    register_update()

    with pytest.raises(ValueError):
        approve_update(
            client_id="client-001",
            update_id="update-001",
            reason="   ",
        )


def test_blank_rejection_reason_is_rejected():
    register_update()

    with pytest.raises(ValueError):
        reject_update(
            client_id="client-001",
            update_id="update-001",
            reason="   ",
        )


def test_blank_quarantine_reason_is_rejected():
    register_update()

    with pytest.raises(ValueError):
        quarantine_update(
            client_id="client-001",
            update_id="update-001",
            reason="   ",
        )


def test_wrong_round_is_not_approved():
    register_update()

    approve_update(
        client_id="client-001",
        update_id="update-001",
        reason="Approved by reviewer.",
    )

    assert not is_approved(
        client_id="client-001",
        update_id="update-001",
        model_version="cnn-v1",
        round_number=2,
        sample_count=1,
        payload_sha256=TEST_DIGEST,
    )


def test_record_retains_decision_reason():
    register_update()

    quarantine_update(
        client_id="client-001",
        update_id="update-001",
        reason="Suspicious update norm.",
    )

    record = get_update_record(
        client_id="client-001",
        update_id="update-001",
    )

    assert record.status == UpdateStatus.QUARANTINED
    assert record.reason == "Suspicious update norm."


def test_approved_status_and_reason_are_persisted():
    register_update()

    approve_update(
        client_id="client-001",
        update_id="update-001",
        reason="Reviewed and accepted.",
    )

    with SessionLocal() as db:
        row = db.scalar(
            select(UpdateApproval).where(
                UpdateApproval.client_id == "client-001",
                UpdateApproval.update_id == "update-001",
            )
        )

    assert row is not None
    assert row.status == UpdateStatus.APPROVED.value
    assert row.reason == "Reviewed and accepted."
    assert row.decided_at is not None


def test_round_must_be_positive():
    with pytest.raises(ValueError, match="round_number must be positive"):
        register_update(round_number=0)


def test_missing_identifier_is_rejected():
    with pytest.raises(ValueError, match="identifiers are required"):
        register_update(update_id=" ")

def test_register_validated_update_preserves_custom_detection_reason():
    record = register_validated_update(
        update_id="update-custom-reason",
        client_id="client-001",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=1, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        reason="Security validation passed; risk_score=0 (LOW). Approval is still required.",
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-detector-v1",
        detector_config={"test_threshold": 1.0},
    )
    assert record.reason == (
        "Security validation passed; risk_score=0 (LOW). Approval is still required."
    )


# ---------------------------------------------------------------------------
# list_pending_updates
# ---------------------------------------------------------------------------

def test_list_pending_empty_initially():
    assert list_pending_updates() == []


def test_list_pending_returns_pending_record():
    register_update()
    pending = list_pending_updates()
    assert len(pending) == 1
    assert pending[0].update_id == "update-001"
    assert pending[0].client_id == "client-001"
    assert pending[0].status == UpdateStatus.PENDING_APPROVAL


def test_list_pending_multiple_records_ordered_by_insertion():
    for i in range(1, 4):
        register_update(
            update_id=f"upd-{i:03d}",
            client_id="client-001",
            payload_sha256="c" * 63 + str(i),
        )
    pending = list_pending_updates()
    assert len(pending) == 3
    assert [r.update_id for r in pending] == ["upd-001", "upd-002", "upd-003"]


def test_list_pending_excludes_approved():
    register_update()
    approve_update(client_id="client-001", update_id="update-001", reason="ok")
    assert list_pending_updates() == []


def test_list_pending_excludes_rejected():
    register_update()
    reject_update(client_id="client-001", update_id="update-001", reason="bad")
    assert list_pending_updates() == []


def test_list_pending_excludes_quarantined():
    register_update()
    quarantine_update(client_id="client-001", update_id="update-001", reason="suspicious")
    assert list_pending_updates() == []


def test_list_pending_respects_limit():
    for i in range(1, 6):
        register_update(
            update_id=f"upd-{i:03d}",
            client_id="client-001",
            payload_sha256="d" * 63 + str(i),
        )
    result = list_pending_updates(limit=3)
    assert len(result) == 3


def test_list_pending_invalid_limit_raises():
    with pytest.raises(ValueError):
        list_pending_updates(limit=0)
    with pytest.raises(ValueError):
        list_pending_updates(limit=1001)


def test_list_pending_non_integer_limit_raises():
    with pytest.raises(TypeError):
        list_pending_updates(limit=1.0)  # type: ignore[arg-type]


def test_approval_is_blocked_when_audit_result_is_not_persisted():
    register_validated_update(
        update_id="update-audit-pending",
        client_id="client-001",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=1, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-detector-v1",
        detector_config={"test_threshold": 1.0},
    )

    record_ingestion_audit_result(
        client_id="client-001",
        update_id="update-audit-pending",
        audit_status="failed",
        audit_failures=("security.anomaly_clean",),
    )

    with pytest.raises(ApprovalError, match="complete detection evidence"):
        approve_update(
            client_id="client-001",
            update_id="update-audit-pending",
            reason="Attempt approval with failed audit.",
        )


def test_historical_record_stays_unassessed_and_cannot_be_approved():
    with SessionLocal() as db, db.begin():
        db.add(
            UpdateApproval(
                client_id="legacy-client",
                update_id="legacy-update",
                model_version="cnn-v1",
                round_number=1,
                sample_count=None,
                payload_sha256=TEST_DIGEST,
                status=UpdateStatus.PENDING_APPROVAL.value,
                reason="Legacy record without detection evidence.",
            )
        )

    record = get_update_record(
        client_id="legacy-client",
        update_id="legacy-update",
    )
    assert record.risk_score is None
    assert record.risk_severity is None
    assert record.suspicious is None
    assert record.anomaly_reasons is None
    assert record.detector_version is None
    assert record.detector_config is None
    assert record.audit_status is None
    assert record.audit_failures is None
    assert not is_approved(
        client_id="legacy-client",
        update_id="legacy-update",
        model_version="cnn-v1",
        round_number=1,
        sample_count=1,
        payload_sha256=TEST_DIGEST,
    )

    with pytest.raises(ApprovalError, match="complete detection evidence"):
        approve_update(
            client_id="legacy-client",
            update_id="legacy-update",
            reason="Must not approve without evidence.",
        )


def test_new_update_requires_explicit_detection_evidence():
    with pytest.raises(TypeError, match="risk_score"):
        register_validated_update(
            update_id="missing-evidence",
            client_id="client-001",
            model_version="cnn-v1",
            round_number=1,
            sample_count_result=SampleCountResult(count=1, provenance=PROVENANCE_CLIENT_CLAIMED),
            payload_sha256=TEST_DIGEST,
        )
