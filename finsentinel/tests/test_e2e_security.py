"""End-to-end security tests covering pipeline gaps not addressed by existing tests.

Existing coverage (do not duplicate):
  test_detection_ingestion_integration.py:
    - Valid update: clean update passes detection, registered pending.
    - Invalid signature: corrupt signature → UpdateAuthenticationError.
    - High-risk quarantine: high-risk update quarantined without approval.
    - Audit database failure: persisted as failed, approval blocked until recovery.
    - Database failure at registration boundary: replay reservation rolled back.
  test_operator_approval_api.py:
    - Unauthorized approval: missing/wrong bearer token → HTTP 401.

Gaps covered here (new tests):
  1. Tampered payload       — payload bytes modified after signing → PayloadIntegrityError.
  2. Duplicate/replayed update — same update_id submitted twice → ReplayProtectionError.
  3. Invalid schema          — valid NPZ but wrong tensor structure → ModelSchemaValidationError.
  4. Rejected update at aggregation gate — rejected update raises AggregationRejectedError.
  5. Payload digest mismatch at aggregation — approved payload A, submitted bytes B →
     AggregationRejectedError (is_approved() checks exact SHA-256).
"""

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
    ReplayProtectionError,
    clear_replay_registry,
)
from enforcement.approval_service import (
    UpdateStatus,
    approve_update,
    clear_approval_registry,
    record_ingestion_audit_result,
    register_validated_update,
    reject_update,
)
from ingestion.payload import PayloadIntegrityError
from ingestion.sample_count_provider import PROVENANCE_CLIENT_CLAIMED, SampleCountResult
from ingestion.schemas import UpdateEnvelope
from ingestion.serialization import serialize_state_dict
from ingestion.service import (
    ModelSchemaValidationError,
    validate_incoming_update,
)
from policy.model_update_policy import ModelUpdatePolicy

TEST_PRIVATE_KEY = Ed25519PrivateKey.generate()
TEST_PUBLIC_KEY = TEST_PRIVATE_KEY.public_key()


def _make_payload(weight_val: float = 1.0) -> bytes:
    return serialize_state_dict(
        {
            "layer.weight": torch.tensor([[weight_val, weight_val]], dtype=torch.float32),
            "layer.bias": torch.tensor([0.1], dtype=torch.float32),
        }
    )


def _make_signed_envelope(
    payload: bytes,
    *,
    client_id: str = "e2e-client",
    update_id: str = "e2e-update",
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
            "signing_key_id": "e2e-key",
        }
    )
    sig = sign_envelope(envelope, TEST_PRIVATE_KEY)
    envelope = envelope.model_copy(update={"signature": sig})

    register_trusted_key(
        key_id="e2e-key",
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


# ---------------------------------------------------------------------------
# 1. Tampered payload
# ---------------------------------------------------------------------------

def test_tampered_payload_raises_payload_integrity_error(
    default_policy: ModelUpdatePolicy,
) -> None:
    """A payload whose bytes differ from the hash in the signed envelope must be
    rejected before any authentication or detection step.

    Scenario: an adversary intercepts the payload in transit and replaces it
    with different bytes.  The original envelope (and its payload_sha256 field)
    is still valid and correctly signed, but the bytes no longer match.
    verify_payload() detects the mismatch and raises PayloadIntegrityError.
    """
    original_payload = _make_payload(weight_val=1.0)
    envelope = _make_signed_envelope(
        original_payload, update_id="tamper-01", client_id="e2e-client"
    )

    # Replace the payload bytes with different content (simulates in-transit tampering).
    tampered_payload = _make_payload(weight_val=999.0)
    assert tampered_payload != original_payload
    # The envelope still carries the hash of the ORIGINAL payload.
    assert hashlib.sha256(tampered_payload).hexdigest() != envelope.payload_sha256

    with pytest.raises(PayloadIntegrityError):
        validate_incoming_update(
            tampered_payload,
            envelope,
            policy=default_policy,
        )


# ---------------------------------------------------------------------------
# 2. Duplicate / replayed update
# ---------------------------------------------------------------------------

def test_duplicate_update_id_raises_replay_protection_error(
    default_policy: ModelUpdatePolicy,
) -> None:
    """Submitting the same (client_id, update_id) a second time must be rejected
    by replay protection before detection runs.

    The first submission reserves the slot in the replay registry and succeeds.
    The second submission sees an already-reserved entry and raises
    ReplayProtectionError — the update is not registered again.
    """
    payload = _make_payload(weight_val=1.0)
    envelope = _make_signed_envelope(
        payload, update_id="replay-01", client_id="e2e-client"
    )

    # First submission: succeeds, registers the update as pending.
    result = validate_incoming_update(payload, envelope, policy=default_policy)
    assert result["approval_status"] == UpdateStatus.PENDING_APPROVAL.value

    # Second submission with the identical (client_id, update_id):
    # The replay registry still holds the reservation, so this must raise.
    envelope2 = _make_signed_envelope(
        payload, update_id="replay-01", client_id="e2e-client"
    )
    with pytest.raises(ReplayProtectionError):
        validate_incoming_update(payload, envelope2, policy=default_policy)


# ---------------------------------------------------------------------------
# 3. Invalid model schema
# ---------------------------------------------------------------------------

def test_invalid_model_schema_raises_model_schema_validation_error(
    default_policy: ModelUpdatePolicy,
) -> None:
    """A payload with an unexpected tensor structure must be rejected after
    deserialization but before detection or approval registration.

    The registered schema for 'cnn-v1' expects 'layer.weight' and 'layer.bias'.
    A payload with 'wrong_layer.weight' and no 'layer.bias' fails schema
    validation and raises ModelSchemaValidationError.
    """
    # Build a payload with wrong tensor names.
    wrong_payload = serialize_state_dict(
        {
            "wrong_layer.weight": torch.tensor([[1.0, 1.0]], dtype=torch.float32),
            "extra.bias": torch.tensor([0.5], dtype=torch.float32),
        }
    )
    envelope = _make_signed_envelope(
        wrong_payload, update_id="schema-fail-01", client_id="e2e-client"
    )

    with pytest.raises(ModelSchemaValidationError):
        validate_incoming_update(
            wrong_payload,
            envelope,
            policy=default_policy,
        )


# ---------------------------------------------------------------------------
# 4. Rejected update reaching aggregation gate
# ---------------------------------------------------------------------------

def test_rejected_update_cannot_enter_aggregation() -> None:
    """An operator-rejected update must be blocked at the aggregation gate.

    After ingestion (pending) and explicit rejection, is_approved() returns
    False for the update's exact identity.  aggregate_approved_updates() must
    raise AggregationRejectedError when it checks approval status.
    """
    payload = _make_payload(weight_val=1.0)
    payload_sha256 = hashlib.sha256(payload).hexdigest()

    register_validated_update(
        update_id="rejected-agg-01",
        client_id="e2e-client",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=5, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=payload_sha256,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
    )
    record_ingestion_audit_result(
        client_id="e2e-client",
        update_id="rejected-agg-01",
        audit_status="persisted",
        audit_failures=(),
    )
    reject_update(
        client_id="e2e-client",
        update_id="rejected-agg-01",
        reason="Rejected by security reviewer for end-to-end test.",
    )

    with pytest.raises(AggregationRejectedError, match="not approved"):
        aggregate_approved_updates(
            [
                ApprovedUpdatePayload(
                    client_id="e2e-client",
                    update_id="rejected-agg-01",
                    model_version="cnn-v1",
                    round_number=1,
                    payload=payload,
                    sample_count=5,
                )
            ],
            expected_state_dict={
                "layer.weight": torch.zeros((1, 2), dtype=torch.float32),
                "layer.bias": torch.zeros(1, dtype=torch.float32),
            },
            model_version="cnn-v1",
            round_number=1,
        )


# ---------------------------------------------------------------------------
# 5. Payload digest mismatch at aggregation
# ---------------------------------------------------------------------------

def test_payload_digest_mismatch_at_aggregation_gate() -> None:
    """The aggregation service rejects an update when the submitted payload bytes
    differ from the bytes that were approved.

    is_approved() verifies the exact SHA-256 of the bytes passed to aggregation.
    An adversary substituting different payload bytes at aggregation time is
    blocked even if the update_id is legitimately approved — because the approval
    is bound to the original digest.
    """
    approved_payload = _make_payload(weight_val=1.0)
    approved_sha256 = hashlib.sha256(approved_payload).hexdigest()

    register_validated_update(
        update_id="digest-mismatch-01",
        client_id="e2e-client",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=5, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=approved_sha256,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
    )
    record_ingestion_audit_result(
        client_id="e2e-client",
        update_id="digest-mismatch-01",
        audit_status="persisted",
        audit_failures=(),
    )
    approve_update(
        client_id="e2e-client",
        update_id="digest-mismatch-01",
        reason="Approved for aggregation mismatch test.",
    )

    # Submit different payload bytes at aggregation time.
    different_payload = _make_payload(weight_val=2.0)
    assert hashlib.sha256(different_payload).hexdigest() != approved_sha256

    with pytest.raises(AggregationRejectedError, match="not approved"):
        aggregate_approved_updates(
            [
                ApprovedUpdatePayload(
                    client_id="e2e-client",
                    update_id="digest-mismatch-01",
                    model_version="cnn-v1",
                    round_number=1,
                    payload=different_payload,
                    sample_count=5,
                )
            ],
            expected_state_dict={
                "layer.weight": torch.zeros((1, 2), dtype=torch.float32),
                "layer.bias": torch.zeros(1, dtype=torch.float32),
            },
            model_version="cnn-v1",
            round_number=1,
        )

    # Confirm that the ORIGINAL payload bytes are still approved.
    aggregate_approved_updates(
        [
            ApprovedUpdatePayload(
                client_id="e2e-client",
                update_id="digest-mismatch-01",
                model_version="cnn-v1",
                round_number=1,
                payload=approved_payload,
                sample_count=5,
            )
        ],
        expected_state_dict={
            "layer.weight": torch.zeros((1, 2), dtype=torch.float32),
            "layer.bias": torch.zeros(1, dtype=torch.float32),
        },
        model_version="cnn-v1",
        round_number=1,
    )
