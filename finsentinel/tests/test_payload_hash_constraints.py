"""Tests for payload hash format enforcement and legacy-record behavior.

Covers:
- Application-layer validation in register_validated_update()
- Legacy NULL records (pre-verification history) cannot pass is_approved()
- Database-level constraint (nullable + format) via ORM-created SQLite schema
- Post-decision audit gap: service layer does not write audit events
"""

import hashlib

import pytest
from sqlalchemy import select

from core.supabase.session import SessionLocal
from db.models.audit_event import AuditEvent
from db.models.update_approval import UpdateApproval
from enforcement.approval_service import (
    ApprovalError,
    UpdateStatus,
    approve_update,
    clear_approval_registry,
    get_update_record,
    is_approved,
    record_ingestion_audit_result,
    register_validated_update,
)
from ingestion.sample_count_provider import PROVENANCE_CLIENT_CLAIMED, SampleCountResult

VALID_HEX_DIGEST = "a" * 64
VALID_MIXED_CASE_DIGEST = "A" * 64  # uppercase — lowercased on insert


@pytest.fixture(autouse=True)
def reset_registry():
    clear_approval_registry()
    yield
    clear_approval_registry()


def _register(
    *,
    update_id: str = "u-hash-001",
    client_id: str = "c-hash-001",
    payload_sha256: str = VALID_HEX_DIGEST,
) -> None:
    register_validated_update(
        update_id=update_id,
        client_id=client_id,
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=1, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=payload_sha256,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
    )


# ---------------------------------------------------------------------------
# Application-layer hash format validation
# ---------------------------------------------------------------------------

def test_valid_64_char_hex_digest_is_accepted() -> None:
    """A correct 64-character lowercase hex SHA-256 digest is accepted."""
    _register(payload_sha256=VALID_HEX_DIGEST)
    record = get_update_record(client_id="c-hash-001", update_id="u-hash-001")
    assert record.payload_sha256 == VALID_HEX_DIGEST


def test_uppercase_hex_digest_is_normalised_to_lowercase() -> None:
    """Uppercase hex digits are accepted and stored normalised to lowercase."""
    _register(payload_sha256=VALID_MIXED_CASE_DIGEST, update_id="u-hash-upper")
    record = get_update_record(client_id="c-hash-001", update_id="u-hash-upper")
    assert record.payload_sha256 == VALID_MIXED_CASE_DIGEST.lower()


def test_digest_with_wrong_length_is_rejected() -> None:
    """A digest that is not exactly 64 characters is rejected."""
    with pytest.raises(ValueError, match="SHA-256"):
        _register(payload_sha256="a" * 63)
    with pytest.raises(ValueError, match="SHA-256"):
        _register(payload_sha256="a" * 65)


def test_non_hex_characters_in_digest_are_rejected() -> None:
    """A 64-character string containing non-hex characters is rejected."""
    with pytest.raises(ValueError, match="SHA-256"):
        _register(payload_sha256="g" * 64)
    with pytest.raises(ValueError, match="SHA-256"):
        _register(payload_sha256="x" * 64)
    with pytest.raises(ValueError, match="SHA-256"):
        _register(payload_sha256=" " * 64)


def test_empty_digest_is_rejected() -> None:
    """An empty string digest is rejected."""
    with pytest.raises(ValueError, match="SHA-256"):
        _register(payload_sha256="")


def test_none_digest_raises() -> None:
    """Passing None as payload_sha256 is rejected."""
    with pytest.raises((ValueError, TypeError)):
        _register(payload_sha256=None)  # type: ignore[arg-type]


def test_real_sha256_hex_digest_is_accepted() -> None:
    """A real SHA-256 hexdigest of a payload is accepted."""
    real_digest = hashlib.sha256(b"test payload bytes").hexdigest()
    _register(payload_sha256=real_digest)
    record = get_update_record(client_id="c-hash-001", update_id="u-hash-001")
    assert record.payload_sha256 == real_digest


# ---------------------------------------------------------------------------
# Legacy NULL records (pre-verification history)
# ---------------------------------------------------------------------------

def _insert_legacy_record(
    *,
    update_id: str = "u-legacy-001",
    client_id: str = "c-legacy-001",
) -> None:
    """Insert a row with NULL payload_sha256 directly (bypassing service validation).

    Simulates a row that existed before migration 312321b36f52 added the
    payload_sha256 column.  After migration e1a2b3c4d5e6 makes the column
    nullable, NULL is the honest representation of an unverifiable hash.
    """
    row = UpdateApproval(
        update_id=update_id,
        client_id=client_id,
        model_version="cnn-v1",
        round_number=1,
        sample_count=None,
        payload_sha256=None,  # unverifiable historical hash
        risk_score=None,
        risk_severity=None,
        suspicious=None,
        anomaly_reasons=None,
        detector_version=None,
        detector_config=None,
        audit_status=None,
        audit_failures=None,
        status=UpdateStatus.PENDING_APPROVAL.value,
        reason="Legacy record predating payload verification.",
    )
    with SessionLocal() as db:
        with db.begin():
            db.add(row)


def test_legacy_null_hash_record_can_be_stored_and_retrieved() -> None:
    """A legacy record with NULL payload_sha256 persists and returns None for the field."""
    _insert_legacy_record()
    record = get_update_record(client_id="c-legacy-001", update_id="u-legacy-001")
    assert record.payload_sha256 is None
    assert record.status == UpdateStatus.PENDING_APPROVAL


def test_legacy_null_hash_cannot_pass_is_approved() -> None:
    """A legacy NULL-hash record cannot be approved for aggregation.

    is_approved() performs WHERE payload_sha256 == <submitted_hash>.
    SQL NULL never equals any string, so the query returns no match.
    Legacy records are correctly blocked from aggregation without any
    additional application-layer guard.
    """
    _insert_legacy_record()
    result = is_approved(
        client_id="c-legacy-001",
        update_id="u-legacy-001",
        model_version="cnn-v1",
        round_number=1,
        payload_sha256=VALID_HEX_DIGEST,
        sample_count=1,
    )
    assert result is False


def test_legacy_null_hash_cannot_be_transitioned_to_approved() -> None:
    """The _transition() approval gate rejects legacy records lacking evidence.

    approve_update() requires complete detection evidence (risk_score,
    audit_status == "persisted", etc.).  A legacy record missing those
    fields cannot be transitioned to APPROVED.
    """
    _insert_legacy_record()
    with pytest.raises(ApprovalError):
        approve_update(
            client_id="c-legacy-001",
            update_id="u-legacy-001",
            reason="Attempting to approve legacy record.",
        )


def test_null_hash_is_accepted_by_orm_check_constraint() -> None:
    """The ORM constraint (payload_sha256 IS NULL OR length = 64) allows NULL.

    NULL represents a legacy, unverifiable record.  It passes the constraint
    so pre-migration rows can be preserved after the nullable migration runs.
    """
    _insert_legacy_record(update_id="u-constraint-null", client_id="c-constraint-001")
    with SessionLocal() as db:
        row = db.scalar(
            select(UpdateApproval).where(
                UpdateApproval.update_id == "u-constraint-null",
                UpdateApproval.client_id == "c-constraint-001",
            )
        )
    assert row is not None
    assert row.payload_sha256 is None


# ---------------------------------------------------------------------------
# Post-decision audit gap: service layer does not write audit events
# ---------------------------------------------------------------------------

def test_approve_update_service_writes_audit_event_atomically() -> None:
    """approve_update() writes an 'operator.update_approved' audit event in the
    same DB transaction as the state transition.

    Both the state change and the audit event are committed together, so they
    are always consistent: a durable approval record always has a matching
    audit event, and a durable audit event always has a matching approval row.

    This applies to every caller — API or direct service call.
    """
    _register()
    record_ingestion_audit_result(
        client_id="c-hash-001",
        update_id="u-hash-001",
        audit_status="persisted",
        audit_failures=(),
    )

    record = approve_update(
        client_id="c-hash-001",
        update_id="u-hash-001",
        reason="Service-layer approval for atomicity test.",
    )
    assert record.status == UpdateStatus.APPROVED

    with SessionLocal() as db:
        row = db.scalar(
            select(UpdateApproval).where(
                UpdateApproval.client_id == "c-hash-001",
                UpdateApproval.update_id == "u-hash-001",
            )
        )
    assert row is not None
    assert row.status == UpdateStatus.APPROVED.value

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == "c-hash-001",
                AuditEvent.update_id == "u-hash-001",
                AuditEvent.event_type == "operator.update_approved",
            )
        ).all()
    assert len(events) == 1
    assert events[0].severity == "info"
