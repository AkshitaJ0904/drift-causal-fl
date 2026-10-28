
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
    quarantine_update,
    register_validated_update,
    reject_update,
)

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
    payload_sha256=TEST_DIGEST,
):
    return register_validated_update(
        update_id=update_id,
        client_id=client_id,
        model_version=model_version,
        round_number=round_number,
        payload_sha256=payload_sha256,
    )


def test_new_update_requires_approval():
    record = register_update()

    assert record.status == UpdateStatus.PENDING_APPROVAL
    assert record.payload_sha256 == TEST_DIGEST
    assert not is_approved(
        client_id="client-001",
        update_id="update-001",
        model_version="cnn-v1",
        round_number=1,
        payload_sha256=TEST_DIGEST,
    )


def test_approval_record_is_persisted_in_database():
    register_update()

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
        payload_sha256="b" * 64,
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
