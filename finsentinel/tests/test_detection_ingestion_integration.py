
"""Integration tests for rule-based anomaly detection during update ingestion."""

import hashlib
from collections.abc import Generator

import pytest
import torch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aggregation.service import (
    AggregationRejectedError,
    ApprovedUpdatePayload,
    aggregate_approved_updates,
)
from core.crypto import sign_envelope
from core.key_registry import clear_trusted_keys, register_trusted_key
from core.model_registry import clear_model_schemas, register_model_schema
from core.replay_protection import (
    clear_replay_registry,
    is_reservation_finalized,
    reserve_update,
)
from detection.rule_based import RuleBasedDetectionConfig
from enforcement.approval_service import (
    ApprovalError,
    UpdateStatus,
    approve_update,
    clear_approval_registry,
    get_update_record,
    is_approved,
)
from ingestion.schemas import UpdateEnvelope
from ingestion.serialization import serialize_state_dict
from ingestion.service import (
    ApprovalRegistrationError,
    UpdateAuthenticationError,
    validate_incoming_update,
)
from policy.model_update_policy import ModelUpdatePolicy

TEST_PRIVATE_KEY = Ed25519PrivateKey.generate()
TEST_PUBLIC_KEY = TEST_PRIVATE_KEY.public_key()


def make_test_payload(weight_val: float = 1.0) -> bytes:
    """Create a serialized state dict with a given weight magnitude."""
    return serialize_state_dict(
        {
            "layer.weight": torch.tensor([[weight_val, weight_val]], dtype=torch.float32),
            "layer.bias": torch.tensor([0.1], dtype=torch.float32),
        }
    )


def make_signed_envelope(
    payload: bytes,
    *,
    client_id: str = "client-001",
    update_id: str = "update-001",
    model_version: str = "cnn-v1",
    round_number: int = 1,
    sample_count: int = 5,
) -> UpdateEnvelope:
    envelope = UpdateEnvelope.model_validate(
        {
            "update_id": update_id,
            "client_id": client_id,
            "model_version": model_version,
            "round_number": round_number,
            "sample_count": sample_count,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
            "created_at": "2026-10-21T10:00:00Z",
            "signature": "placeholder",
            "signing_key_id": "key-001",
        }
    )
    sig = sign_envelope(envelope, TEST_PRIVATE_KEY)
    envelope = envelope.model_copy(update={"signature": sig})

    register_trusted_key(
        key_id="key-001",
        client_id=client_id,
        public_key=TEST_PUBLIC_KEY,
        max_sample_count=10_000,
    )
    return envelope


@pytest.fixture(autouse=True)
def reset_registries() -> Generator[None, None, None]:
    clear_trusted_keys()
    clear_replay_registry()
    clear_approval_registry()
    clear_model_schemas()

    register_model_schema(
        model_version="cnn-v1",
        state_dict={
            "layer.weight": torch.zeros((1, 2), dtype=torch.float32),
            "layer.bias": torch.zeros(1, dtype=torch.float32),
        },
    )

    yield

    clear_trusted_keys()
    clear_replay_registry()
    clear_approval_registry()
    clear_model_schemas()


@pytest.fixture
def default_policy() -> ModelUpdatePolicy:
    return ModelUpdatePolicy(
        allowed_model_versions=frozenset(["cnn-v1"]),
        allowed_round_numbers=frozenset([1]),
        max_update_age_seconds=86400 * 365 * 10,
        max_future_clock_skew_seconds=86400 * 365 * 10,
    )


def test_clean_update_passes_detection_and_registers_pending(
    default_policy: ModelUpdatePolicy,
) -> None:
    payload = make_test_payload(weight_val=1.0)
    envelope = make_signed_envelope(payload, update_id="clean-01")

    config = RuleBasedDetectionConfig(
        max_weight_l2_norm=50.0,
        max_weight_abs_mean=10.0,
    )

    result = validate_incoming_update(
        payload,
        envelope,
        policy=default_policy,
        detection_config=config,
    )

    assert result["ingestion_status"] == "validated"
    assert result["approval_status"] == UpdateStatus.PENDING_APPROVAL.value
    assert result["risk_score"] == 0
    assert result["severity"] == "LOW"
    assert result["suspicious"] is False
    assert result["anomaly_reasons"] == []
    assert result["audit_status"] == "persisted"
    assert result["audit_failures"] == []

    # Verify persisted reason in update_approvals
    record = get_update_record(client_id="client-001", update_id="clean-01")
    assert record.status == UpdateStatus.PENDING_APPROVAL
    assert "risk_score=0 (LOW)" in record.reason
    assert record.risk_score == 0
    assert record.risk_severity == "LOW"
    assert record.suspicious is False
    assert record.anomaly_reasons == ()
    assert record.detector_version == "rule-based-v1"
    assert record.detector_config is not None
    assert record.detector_config["high_risk_action"] == "quarantined"

    # Verify reservation is finalized
    assert is_reservation_finalized(client_id="client-001", update_id="clean-01") is True


def test_high_risk_update_is_quarantined_without_approval(
    default_policy: ModelUpdatePolicy,
) -> None:
    # Large weights: [[100.0, 100.0]] -> L2 norm = sqrt(20000) ~ 141.4 > 10.0
    payload = make_test_payload(weight_val=100.0)
    envelope = make_signed_envelope(payload, update_id="suspicious-01")

    config = RuleBasedDetectionConfig(
        max_weight_l2_norm=10.0,
        max_weight_abs_mean=5.0,
    )

    result = validate_incoming_update(
        payload,
        envelope,
        policy=default_policy,
        detection_config=config,
    )

    assert result["ingestion_status"] == "validated"
    assert result["approval_status"] == UpdateStatus.QUARANTINED.value
    assert result["risk_score"] >= 50  # type: ignore[operator]
    assert result["suspicious"] is True
    assert len(result["anomaly_reasons"]) >= 1  # type: ignore[arg-type]

    # High-risk updates are quarantined, never approved or admitted to aggregation.
    assert not is_approved(
        client_id="client-001",
        update_id="suspicious-01",
        model_version="cnn-v1",
        round_number=1,
        sample_count=envelope.sample_count,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )

    record = get_update_record(client_id="client-001", update_id="suspicious-01")
    assert record.status == UpdateStatus.QUARANTINED
    assert "ANOMALY FLAGGED" in record.reason
    assert record.risk_score is not None
    assert record.risk_score >= 50
    assert record.risk_severity == "HIGH"
    assert record.suspicious is True
    assert record.anomaly_reasons
    assert record.detector_config is not None
    assert record.detector_config["max_weight_l2_norm"] == 10.0


def test_clean_update_requires_explicit_approval_before_aggregation(
    default_policy: ModelUpdatePolicy,
) -> None:
    payload = make_test_payload(weight_val=1.0)
    envelope = make_signed_envelope(payload, update_id="approved-e2e-01")
    result = validate_incoming_update(
        payload,
        envelope,
        policy=default_policy,
        detection_config=RuleBasedDetectionConfig(
            max_weight_l2_norm=50.0,
            max_weight_abs_mean=10.0,
        ),
    )

    assert result["approval_status"] == UpdateStatus.PENDING_APPROVAL.value
    with pytest.raises(AggregationRejectedError, match="not approved"):
        aggregate_approved_updates(
            [
                ApprovedUpdatePayload(
                    client_id="client-001",
                    update_id="approved-e2e-01",
                    model_version="cnn-v1",
                    round_number=1,
                    payload=payload,
                    sample_count=envelope.sample_count,
                )
            ],
            expected_state_dict={
                "layer.weight": torch.zeros((1, 2), dtype=torch.float32),
                "layer.bias": torch.zeros(1, dtype=torch.float32),
            },
            model_version="cnn-v1",
            round_number=1,
        )

    approve_update(
        client_id="client-001",
        update_id="approved-e2e-01",
        reason="Explicit reviewer approval for end-to-end test.",
    )
    aggregated = aggregate_approved_updates(
        [
            ApprovedUpdatePayload(
                client_id="client-001",
                update_id="approved-e2e-01",
                model_version="cnn-v1",
                round_number=1,
                payload=payload,
                sample_count=envelope.sample_count,
            )
        ],
        expected_state_dict={
            "layer.weight": torch.zeros((1, 2), dtype=torch.float32),
            "layer.bias": torch.zeros(1, dtype=torch.float32),
        },
        model_version="cnn-v1",
        round_number=1,
    )
    assert torch.equal(
        aggregated["layer.weight"],
        torch.tensor([[1.0, 1.0]], dtype=torch.float32),
    )


def test_hard_validation_failure_aborts_before_detection(
    default_policy: ModelUpdatePolicy,
) -> None:
    payload = make_test_payload(weight_val=1.0)
    envelope = make_signed_envelope(payload)

    # Corrupt the signature
    envelope = envelope.model_copy(update={"signature": "bad-signature"})

    with pytest.raises(UpdateAuthenticationError):
        validate_incoming_update(payload, envelope, policy=default_policy)


def test_replay_reservation_rollback_on_database_registration_failure(
    default_policy: ModelUpdatePolicy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = make_test_payload(weight_val=1.0)
    envelope = make_signed_envelope(payload, update_id="rollback-01")

    # Force registration to fail as though the DB could not write the row.
    # Patch the name imported in ingestion.service, not the source module.
    def mock_register(*args, **kwargs):
        raise ApprovalError("Simulated DB connection failure")

    import ingestion.service as ingestion_service_mod
    monkeypatch.setattr(
        ingestion_service_mod, "register_and_finalize_validated_update", mock_register
    )

    with pytest.raises(ApprovalRegistrationError):
        validate_incoming_update(payload, envelope, policy=default_policy)

    # Replay reservation must have been rolled back, allowing immediate reservation/retry
    # If rollback failed, reserve_update would raise ReplayProtectionError
    reserve_update(envelope)


def test_audit_persistence_failure_reports_failed_status_and_preserves_approval(
    default_policy: ModelUpdatePolicy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = make_test_payload(weight_val=1.0)
    envelope = make_signed_envelope(payload, update_id="audit-fail-01")

    # Mock audit service to raise SQLAlchemyError simulating audit DB table outage.
    # Must patch the name as imported in ingestion.service, not the source module,
    # because ingestion/service.py uses `from audit.service import record_audit_event`.
    from sqlalchemy.exc import OperationalError
    def mock_audit(*args, **kwargs):
        raise OperationalError("audit connection lost", params=None, orig=Exception())

    import ingestion.service as ingestion_service_mod
    monkeypatch.setattr(ingestion_service_mod, "record_audit_event", mock_audit)

    result = validate_incoming_update(
        payload,
        envelope,
        policy=default_policy,
    )

    # Explicit audit failure reporting: must not pretend auditing succeeded
    assert result["audit_status"] == "failed"
    assert len(result["audit_failures"]) > 0  # type: ignore[arg-type]

    # Invariants preserved: update is still pending approval, aggregation unauthorized
    assert result["ingestion_status"] == "validated"
    assert result["approval_status"] == UpdateStatus.PENDING_APPROVAL.value
    assert result["aggregation_status"] == "not_authorized"

    record = get_update_record(client_id="client-001", update_id="audit-fail-01")
    assert record.status == UpdateStatus.PENDING_APPROVAL
    assert record.audit_status == "failed"
    assert record.audit_failures
    assert "AUDIT_PERSISTENCE_FAILED" in record.reason
    with pytest.raises(ApprovalError, match="persisted audit status"):
        from enforcement.approval_service import approve_update

        approve_update(
            client_id="client-001",
            update_id="audit-fail-01",
            reason="Approval must wait for audit recovery.",
        )
