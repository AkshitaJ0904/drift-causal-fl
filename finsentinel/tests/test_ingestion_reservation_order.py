"""Ingestion ordering and replay-finalization failure tests."""

import hashlib
from types import SimpleNamespace

import pytest

import ingestion.service as ingestion_service
from core.replay_protection import ReplayProtectionError
from detection.rule_based import RuleBasedDetectionConfig
from enforcement.approval_service import UpdateStatus
from ingestion.schemas import UpdateEnvelope
from ingestion.service import (
    ApprovalRegistrationError,
    DetectionConfigurationError,
    validate_incoming_update,
)
from policy.model_update_policy import ModelUpdatePolicy


@pytest.fixture
def prepared_ingestion(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[str], UpdateEnvelope]:
    calls: list[str] = []
    envelope = UpdateEnvelope.model_validate(
        {
            "update_id": "update-order-001",
            "client_id": "client-001",
            "model_version": "cnn-v1",
            "round_number": 1,
            "sample_count": 1,
            "payload_sha256": hashlib.sha256(b"payload").hexdigest(),
            "payload_size_bytes": len(b"payload"),
            "created_at": "2026-10-21T10:00:00Z",
            "signature": "test-signature",
            "signing_key_id": "key-001",
        }
    )
    monkeypatch.setattr(
        ingestion_service,
        "verify_payload",
        lambda payload, submitted: envelope.payload_sha256,
    )
    monkeypatch.setattr(
        ingestion_service,
        "get_trusted_key",
        lambda key_id: SimpleNamespace(
            client_id="client-001",
            public_key=object(),
            max_sample_count=100,
        ),
    )
    monkeypatch.setattr(ingestion_service, "verify_envelope_signature", lambda *args: True)
    monkeypatch.setattr(
        ingestion_service,
        "deserialize_state_dict",
        lambda *args, **kwargs: {"weight": object()},
    )
    monkeypatch.setattr(
        ingestion_service,
        "validate_against_registered_schema",
        lambda *args, **kwargs: SimpleNamespace(accepted=True, reason=""),
    )
    monkeypatch.setattr(
        ingestion_service,
        "evaluate_update_policy",
        lambda *args: SimpleNamespace(accepted=True, reason="", reason_code=""),
    )
    monkeypatch.setattr(
        ingestion_service,
        "record_audit_event",
        lambda **kwargs: calls.append(f"audit:{kwargs['event_type']}"),
    )
    def _stub_reserve(submitted: object) -> str:
        calls.append("reserve")
        return "reservation-token"

    def _stub_extract(*args: object, **kwargs: object) -> dict[str, float]:
        calls.append("extract")
        return {"weight_l2_norm": 1.0}

    def _stub_detect(*args: object, **kwargs: object) -> SimpleNamespace:
        calls.append("detect")
        return SimpleNamespace(risk_score=0, severity="LOW", suspicious=False, reasons=[])

    def _stub_register(**kwargs: object) -> SimpleNamespace:
        calls.append("register")
        return SimpleNamespace(status=UpdateStatus.PENDING_APPROVAL)

    def _stub_release(**kwargs: object) -> bool:
        calls.append("release")
        return True

    monkeypatch.setattr(ingestion_service, "reserve_update", _stub_reserve)
    monkeypatch.setattr(ingestion_service, "extract_update_features", _stub_extract)
    monkeypatch.setattr(ingestion_service, "detect_update_anomalies", _stub_detect)
    monkeypatch.setattr(ingestion_service, "register_and_finalize_validated_update", _stub_register)
    monkeypatch.setattr(
        ingestion_service,
        "mark_reservation_finalized_in_memory",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(ingestion_service, "release_update_reservation", _stub_release)
    monkeypatch.setattr(
        ingestion_service,
        "record_ingestion_audit_result",
        lambda **kwargs: calls.append("persist_audit"),
    )
    return calls, envelope


_DEFAULT_DETECTION_CONFIG = RuleBasedDetectionConfig(max_weight_l2_norm=10.0)


def run_prepared_update(
    calls: list[str],
    envelope: UpdateEnvelope,
    detection_config: RuleBasedDetectionConfig | None = _DEFAULT_DETECTION_CONFIG,
) -> dict[str, object]:
    return validate_incoming_update(
        b"payload",
        envelope,
        policy=ModelUpdatePolicy(
            allowed_model_versions=frozenset({"cnn-v1"}),
            allowed_round_numbers=frozenset({1}),
            max_update_age_seconds=10_000_000_000,
            max_future_clock_skew_seconds=10_000_000_000,
        ),
        detection_config=detection_config,
    )


def test_replay_reservation_precedes_feature_extraction_and_detection(
    prepared_ingestion: tuple[list[str], UpdateEnvelope],
) -> None:
    calls, envelope = prepared_ingestion
    result = run_prepared_update(calls, envelope)

    assert calls.index("reserve") < calls.index("extract")
    assert calls.index("reserve") < calls.index("detect")
    assert calls.index("detect") < calls.index("register")
    assert result["approval_status"] == UpdateStatus.PENDING_APPROVAL.value


def test_replay_rejection_stops_before_feature_extraction(
    prepared_ingestion: tuple[list[str], UpdateEnvelope],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, envelope = prepared_ingestion

    def reject_replay(envelope: UpdateEnvelope) -> str:
        calls.append("reserve")
        raise ReplayProtectionError("Duplicate update detected")

    monkeypatch.setattr(ingestion_service, "reserve_update", reject_replay)

    with pytest.raises(ReplayProtectionError):
        run_prepared_update(calls, envelope)

    assert "extract" not in calls
    assert "detect" not in calls
    assert "register" not in calls


def test_combined_registration_failure_releases_reservation(
    prepared_ingestion: tuple[list[str], UpdateEnvelope],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """register_and_finalize_validated_update() failure rolls back atomically.

    Because approval INSERT and replay finalization are a single transaction,
    any failure means NEITHER was committed.  The ingestion service must release
    the reservation so the client can retry, unlike the old two-step design where
    a finalization failure after a successful registration required the reservation
    to remain held.
    """
    calls, envelope = prepared_ingestion

    def fail_combined(**kwargs):
        calls.append("register")
        from sqlalchemy.exc import OperationalError
        raise OperationalError("simulated combined tx failure", params=None, orig=Exception())

    monkeypatch.setattr(
        ingestion_service,
        "register_and_finalize_validated_update",
        fail_combined,
    )

    with pytest.raises(ApprovalRegistrationError):
        run_prepared_update(calls, envelope)

    assert "register" in calls
    assert "release" in calls
    assert "audit:security.approval_registration_failed" in calls


def test_database_registration_error_releases_owned_reservation(
    prepared_ingestion: tuple[list[str], UpdateEnvelope],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, envelope = prepared_ingestion

    def fail_registration(**kwargs):
        calls.append("register")
        from sqlalchemy.exc import OperationalError

        raise OperationalError("database unavailable", params=None, orig=Exception())

    monkeypatch.setattr(
        ingestion_service, "register_and_finalize_validated_update", fail_registration
    )

    with pytest.raises(ApprovalRegistrationError):
        run_prepared_update(calls, envelope)

    assert "release" in calls
    assert "finalize" not in calls


def test_missing_required_detection_configuration_releases_reservation(
    prepared_ingestion: tuple[list[str], UpdateEnvelope],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, envelope = prepared_ingestion

    def missing_config():
        raise ValueError("thresholds are missing")

    monkeypatch.setattr(ingestion_service, "get_detection_config", missing_config)

    with pytest.raises(DetectionConfigurationError):
        run_prepared_update(calls, envelope, detection_config=None)

    assert "reserve" in calls
    assert "release" in calls
    assert "extract" not in calls
    assert "register" not in calls


def test_high_risk_result_is_quarantined_and_never_approved(
    prepared_ingestion: tuple[list[str], UpdateEnvelope],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, envelope = prepared_ingestion
    monkeypatch.setattr(
        ingestion_service,
        "detect_update_anomalies",
        lambda *args, **kwargs: SimpleNamespace(
            risk_score=75,
            severity="HIGH",
            suspicious=True,
            reasons=("test threshold exceeded",),
        ),
    )

    def register(**kwargs):
        calls.append("register")
        assert kwargs["initial_status"] == "quarantined"
        return SimpleNamespace(status=UpdateStatus.QUARANTINED)

    monkeypatch.setattr(
        ingestion_service, "register_and_finalize_validated_update", register
    )

    result = run_prepared_update(calls, envelope)

    assert result["approval_status"] == UpdateStatus.QUARANTINED.value
    assert result["aggregation_status"] == "not_authorized"
    assert "audit:security.update_quarantined" in calls
    assert "audit:security.update_pending_approval" not in calls


def test_ambiguous_commit_recovery_does_not_raise(
    prepared_ingestion: tuple[list[str], UpdateEnvelope],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When register_and_finalize_validated_update raises SQLAlchemyError but
    the DB transaction already committed, the ingestion service must NOT raise
    ApprovalRegistrationError.

    This covers the ambiguous-commit scenario:
      1. The combined DB transaction commits successfully.
      2. The connection drops before Python receives the acknowledgment.
      3. Python raises SQLAlchemyError (or OperationalError).
      4. release_update_reservation() finds the DB row finalized=True,
         returns False, and syncs entry.finalized=True.
      5. is_reservation_finalized() returns True.
      6. get_update_record() finds the approval row in the DB.
      7. The service recovers and continues on the success path.
    """
    from sqlalchemy.exc import OperationalError

    calls, envelope = prepared_ingestion

    def fail_after_commit(**kwargs):
        calls.append("register")
        raise OperationalError("connection lost after commit", params=None, orig=Exception())

    monkeypatch.setattr(
        ingestion_service,
        "register_and_finalize_validated_update",
        fail_after_commit,
    )
    # Simulate release refusing because the DB row is finalized (ambiguous commit).
    def _stub_release_false(**kwargs: object) -> bool:
        calls.append("release")
        return False

    monkeypatch.setattr(ingestion_service, "release_update_reservation", _stub_release_false)
    # is_reservation_finalized returns True: the DB row is finalized.
    monkeypatch.setattr(
        ingestion_service,
        "is_reservation_finalized",
        lambda **kwargs: True,
    )
    # get_update_record returns the approval record (it committed to the DB).
    # Fields must match the in-flight request so the cross-verification passes.
    recovered = SimpleNamespace(
        status=UpdateStatus.PENDING_APPROVAL,
        payload_sha256=envelope.payload_sha256,
        model_version=envelope.model_version,
        round_number=envelope.round_number,
    )
    monkeypatch.setattr(
        ingestion_service,
        "get_update_record",
        lambda **kwargs: recovered,
    )

    # Must NOT raise ApprovalRegistrationError — the commit succeeded.
    result = run_prepared_update(calls, envelope)

    assert result["approval_status"] == UpdateStatus.PENDING_APPROVAL.value
    assert "register" in calls
    assert "release" in calls
    # The release attempted but was refused (returned False, DB row was finalized).
    # The service must have recovered via ambiguous-commit reconciliation.
    assert "audit:security.approval_registration_failed" not in calls


def test_ambiguous_commit_no_approval_record_raises(
    prepared_ingestion: tuple[list[str], UpdateEnvelope],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When release_update_reservation returns False, the reservation is finalized,
    but no approval record exists in the DB, the service must raise
    ApprovalRegistrationError and require manual review.

    This is the pathological case where the replay record is finalized but the
    approval INSERT was not committed — an internal consistency error that the
    service cannot recover from automatically.
    """
    from sqlalchemy.exc import OperationalError

    from enforcement.approval_service import ApprovalError

    calls, envelope = prepared_ingestion

    def fail_registration(**kwargs):
        calls.append("register")
        raise OperationalError("connection lost", params=None, orig=Exception())

    monkeypatch.setattr(
        ingestion_service,
        "register_and_finalize_validated_update",
        fail_registration,
    )
    def _stub_release_false_2(**kwargs: object) -> bool:
        calls.append("release")
        return False

    monkeypatch.setattr(ingestion_service, "release_update_reservation", _stub_release_false_2)
    monkeypatch.setattr(
        ingestion_service,
        "is_reservation_finalized",
        lambda **kwargs: True,
    )
    # Approval record is NOT in the DB (get_update_record raises ApprovalError).
    def fail_get_record(**kwargs):
        raise ApprovalError("Unknown update.")

    monkeypatch.setattr(
        ingestion_service,
        "get_update_record",
        fail_get_record,
    )

    with pytest.raises(ApprovalRegistrationError):
        run_prepared_update(calls, envelope)

    assert "register" in calls
    assert "audit:security.approval_registration_failed" in calls
