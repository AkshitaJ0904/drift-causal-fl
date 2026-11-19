
"""Entry 34 Section 4 — End-to-end aggregation verification for coordinator_verified mode.

Implements the missing Entry 33 scenario: a provider-verified update goes through
the full validate_incoming_update() pipeline (payload deserialization, DB-backed
schema validation, replay protection) and is correctly aggregated via weighted FedAvg.

Previous Entry 33 tests used register_validated_update() directly, bypassing
validate_incoming_update().  The DB-backed schema lookup in validate_against_registered_schema()
was therefore not exercised in an end-to-end test for a provider-verified update.
These tests close that gap.

Three scenarios:
1. Single provider-verified update: full pipeline → approve → aggregate → verify FedAvg.
2. Two provider-verified updates with different sample counts: verify weighted FedAvg math.
3. CLIENT_CLAIMED update submitted via full pipeline: rejected at aggregation gate in
   coordinator_verified mode.

PostgreSQL status: Unavailable.  All results are SQLite (StaticPool from conftest.py).
"""

from __future__ import annotations

import hashlib

import pytest
import torch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aggregation.service import (
    AggregationRejectedError,
    ApprovedUpdatePayload,
    aggregate_approved_updates,
)
from core.config import TRUST_MODE_COORDINATOR_VERIFIED
from core.crypto import sign_envelope
from core.key_registry import clear_trusted_keys, register_trusted_key
from core.model_registry import clear_model_schemas, register_model_schema
from core.replay_protection import clear_replay_registry
from enforcement.approval_service import (
    UpdateStatus,
    approve_update,
    clear_approval_registry,
    get_update_record,
)
from ingestion.sample_count_provider import (
    PROVENANCE_CLIENT_CLAIMED,
    PROVENANCE_PROVIDER_VERIFIED,
)
from ingestion.schemas import UpdateEnvelope
from ingestion.serialization import serialize_state_dict
from ingestion.service import configure_sample_count_provider, validate_incoming_update
from policy.model_update_policy import ModelUpdatePolicy

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENV_VAR = "FINSENTINEL_SAMPLE_COUNT_TRUST_MODE"
_MODEL_VERSION = "cnn-v1"
_ROUND_NUMBER = 1

# Trusted model schema: layer.weight (1, 2) float32 + layer.bias (1,) float32.
# Shape must match the payload tensors produced by _make_payload().
_SCHEMA_STATE_DICT = {
    "layer.weight": torch.zeros((1, 2), dtype=torch.float32),
    "layer.bias": torch.zeros(1, dtype=torch.float32),
}

# ---------------------------------------------------------------------------
# Test-only provider doubles
# ---------------------------------------------------------------------------


class _FixedProvider:
    """Returns a fixed sample count so the update gets PROVIDER_VERIFIED."""

    name = "e2e-fixed-provider"

    def __init__(self, count: int) -> None:
        self._count = count

    def get_verified_count(self, *, client_id, update_id, round_number) -> int | None:
        return self._count


class _PerUpdateProvider:
    """Returns a per-update_id sample count so multiple updates get PROVIDER_VERIFIED."""

    name = "e2e-per-update-provider"

    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts

    def get_verified_count(self, *, client_id, update_id, round_number) -> int | None:
        return self._counts.get(update_id)


# ---------------------------------------------------------------------------
# Payload and envelope helpers
# ---------------------------------------------------------------------------

_PRIVATE_KEY = Ed25519PrivateKey.generate()
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


def _make_payload(weight_val: float = 1.0) -> bytes:
    return serialize_state_dict(
        {
            "layer.weight": torch.tensor([[weight_val, weight_val]], dtype=torch.float32),
            "layer.bias": torch.tensor([0.1], dtype=torch.float32),
        }
    )


def _register_key_and_make_envelope(
    payload: bytes,
    *,
    client_id: str,
    update_id: str,
    sample_count: int,
    key_id: str = "e2e-key-001",
) -> UpdateEnvelope:
    """Register a trusted signing key and return a correctly signed envelope."""
    envelope = UpdateEnvelope.model_validate(
        {
            "update_id": update_id,
            "client_id": client_id,
            "model_version": _MODEL_VERSION,
            "round_number": _ROUND_NUMBER,
            "sample_count": sample_count,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
            "created_at": "2026-10-21T10:00:00Z",
            "signature": "placeholder",
            "signing_key_id": key_id,
        }
    )
    sig = sign_envelope(envelope, _PRIVATE_KEY)
    envelope = envelope.model_copy(update={"signature": sig})
    register_trusted_key(
        key_id=key_id,
        client_id=client_id,
        public_key=_PUBLIC_KEY,
        max_sample_count=10_000,
    )
    return envelope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registries():
    """Clear all DB-backed registries before and after each test.

    Also registers the cnn-v1 model schema so validate_against_registered_schema()
    finds a trusted schema during ingestion.  This is the state that was absent in
    Entry 33 — that gap is what these tests close.
    """
    clear_trusted_keys()
    clear_replay_registry()
    clear_approval_registry()
    clear_model_schemas()
    configure_sample_count_provider(None)

    register_model_schema(model_version=_MODEL_VERSION, state_dict=_SCHEMA_STATE_DICT)

    yield

    clear_trusted_keys()
    clear_replay_registry()
    clear_approval_registry()
    clear_model_schemas()
    configure_sample_count_provider(None)


@pytest.fixture
def default_policy() -> ModelUpdatePolicy:
    return ModelUpdatePolicy(
        allowed_model_versions=frozenset([_MODEL_VERSION]),
        allowed_round_numbers=frozenset([_ROUND_NUMBER]),
        max_update_age_seconds=86400 * 365 * 10,
        max_future_clock_skew_seconds=86400 * 365 * 10,
    )


# ---------------------------------------------------------------------------
# 1. Full pipeline: provider-verified update → approve → aggregate → FedAvg
# ---------------------------------------------------------------------------


def test_e2e_provider_verified_update_full_pipeline(
    monkeypatch,
    default_policy: ModelUpdatePolicy,
) -> None:
    """Full E2E: DB schema registration → validate_incoming_update() (includes
    DB-backed schema validation) → verify PROVIDER_VERIFIED persisted in DB →
    approve in coordinator_verified mode → aggregate → verify FedAvg result.

    This is the scenario that was missing from Entry 33: schema validation from the DB
    is exercised inside validate_incoming_update() for a provider-verified update.
    """
    monkeypatch.setenv(_ENV_VAR, TRUST_MODE_COORDINATOR_VERIFIED)
    sample_count = 100
    configure_sample_count_provider(_FixedProvider(sample_count))

    payload = _make_payload(weight_val=2.0)
    envelope = _register_key_and_make_envelope(
        payload,
        client_id="e2e-pv-client",
        update_id="e2e-pv-upd-001",
        sample_count=sample_count,
    )

    # Step 1: Submit via full ingestion pipeline.
    # validate_incoming_update() calls validate_against_registered_schema() which
    # reads the trusted schema from the DB (registered by the fixture above).
    result = validate_incoming_update(
        payload,
        envelope,
        policy=default_policy,
        trust_mode=TRUST_MODE_COORDINATOR_VERIFIED,
    )
    assert result["ingestion_status"] == "validated"
    assert result["schema_status"] == "verified"
    assert result["approval_status"] == UpdateStatus.PENDING_APPROVAL.value

    # Step 2: Verify persisted provenance and sample count in the DB.
    record = get_update_record(client_id="e2e-pv-client", update_id="e2e-pv-upd-001")
    assert record.sample_count_provenance == PROVENANCE_PROVIDER_VERIFIED
    assert record.sample_count == sample_count

    # Step 3: Approve in coordinator_verified mode.
    # approve_update() reads the env var, confirms PROVIDER_VERIFIED in the DB,
    # then transitions the record to APPROVED.
    approved = approve_update(
        client_id="e2e-pv-client",
        update_id="e2e-pv-upd-001",
        reason="e2e test approval",
    )
    assert approved.status == UpdateStatus.APPROVED
    assert approved.sample_count_provenance == PROVENANCE_PROVIDER_VERIFIED

    # Step 4: Execute aggregation and verify weighted FedAvg result.
    # With a single update (sample_count=100, weight=[[2.0, 2.0]], bias=[0.1]):
    # FedAvg = that update's tensors.
    aggregated = aggregate_approved_updates(
        [
            ApprovedUpdatePayload(
                client_id="e2e-pv-client",
                update_id="e2e-pv-upd-001",
                model_version=_MODEL_VERSION,
                round_number=_ROUND_NUMBER,
                payload=payload,
                sample_count=sample_count,
                sample_count_provenance=PROVENANCE_PROVIDER_VERIFIED,
            )
        ],
        expected_state_dict=_SCHEMA_STATE_DICT,
        model_version=_MODEL_VERSION,
        round_number=_ROUND_NUMBER,
    )

    assert torch.allclose(
        aggregated["layer.weight"],
        torch.tensor([[2.0, 2.0]], dtype=torch.float32),
    )
    assert torch.allclose(
        aggregated["layer.bias"],
        torch.tensor([0.1], dtype=torch.float32),
    )


# ---------------------------------------------------------------------------
# 2. Weighted FedAvg with two provider-verified updates
# ---------------------------------------------------------------------------


def test_e2e_weighted_fedavg_two_provider_verified_updates(
    monkeypatch,
    default_policy: ModelUpdatePolicy,
) -> None:
    """Weighted FedAvg with two provider-verified updates in coordinator_verified mode.

    Update A: weight=[[2.0, 2.0]], bias=[0.1], sample_count=100
    Update B: weight=[[4.0, 4.0]], bias=[0.1], sample_count=300

    Expected FedAvg:
      layer.weight = (100*[[2.0,2.0]] + 300*[[4.0,4.0]]) / 400 = [[3.5, 3.5]]
      layer.bias   = (100*[0.1]        + 300*[0.1])        / 400 = [0.1]
    """
    monkeypatch.setenv(_ENV_VAR, TRUST_MODE_COORDINATOR_VERIFIED)

    configure_sample_count_provider(
        _PerUpdateProvider(
            {
                "e2e-pv-upd-a": 100,
                "e2e-pv-upd-b": 300,
            }
        )
    )

    payload_a = _make_payload(weight_val=2.0)
    payload_b = _make_payload(weight_val=4.0)

    envelope_a = _register_key_and_make_envelope(
        payload_a,
        client_id="e2e-pv-client-a",
        update_id="e2e-pv-upd-a",
        sample_count=100,
        key_id="e2e-key-a",
    )
    envelope_b = _register_key_and_make_envelope(
        payload_b,
        client_id="e2e-pv-client-b",
        update_id="e2e-pv-upd-b",
        sample_count=300,
        key_id="e2e-key-b",
    )

    # Submit both updates via full ingestion pipeline.
    result_a = validate_incoming_update(
        payload_a,
        envelope_a,
        policy=default_policy,
        trust_mode=TRUST_MODE_COORDINATOR_VERIFIED,
    )
    result_b = validate_incoming_update(
        payload_b,
        envelope_b,
        policy=default_policy,
        trust_mode=TRUST_MODE_COORDINATOR_VERIFIED,
    )
    assert result_a["ingestion_status"] == "validated"
    assert result_b["ingestion_status"] == "validated"

    # Verify both have PROVIDER_VERIFIED provenance in the DB.
    record_a = get_update_record(client_id="e2e-pv-client-a", update_id="e2e-pv-upd-a")
    record_b = get_update_record(client_id="e2e-pv-client-b", update_id="e2e-pv-upd-b")
    assert record_a.sample_count_provenance == PROVENANCE_PROVIDER_VERIFIED
    assert record_a.sample_count == 100
    assert record_b.sample_count_provenance == PROVENANCE_PROVIDER_VERIFIED
    assert record_b.sample_count == 300

    # Approve both.
    approve_update(client_id="e2e-pv-client-a", update_id="e2e-pv-upd-a", reason="test")
    approve_update(client_id="e2e-pv-client-b", update_id="e2e-pv-upd-b", reason="test")

    # Aggregate and verify weighted FedAvg.
    aggregated = aggregate_approved_updates(
        [
            ApprovedUpdatePayload(
                client_id="e2e-pv-client-a",
                update_id="e2e-pv-upd-a",
                model_version=_MODEL_VERSION,
                round_number=_ROUND_NUMBER,
                payload=payload_a,
                sample_count=100,
                sample_count_provenance=PROVENANCE_PROVIDER_VERIFIED,
            ),
            ApprovedUpdatePayload(
                client_id="e2e-pv-client-b",
                update_id="e2e-pv-upd-b",
                model_version=_MODEL_VERSION,
                round_number=_ROUND_NUMBER,
                payload=payload_b,
                sample_count=300,
                sample_count_provenance=PROVENANCE_PROVIDER_VERIFIED,
            ),
        ],
        expected_state_dict=_SCHEMA_STATE_DICT,
        model_version=_MODEL_VERSION,
        round_number=_ROUND_NUMBER,
    )

    # (100 * [[2.0,2.0]] + 300 * [[4.0,4.0]]) / 400 = [[3.5, 3.5]]
    expected_weight = torch.tensor([[3.5, 3.5]], dtype=torch.float32)
    expected_bias = torch.tensor([0.1], dtype=torch.float32)

    assert torch.allclose(aggregated["layer.weight"].to(torch.float32), expected_weight)
    assert torch.allclose(aggregated["layer.bias"].to(torch.float32), expected_bias)


# ---------------------------------------------------------------------------
# 3. CLIENT_CLAIMED update rejected at aggregation in coordinator_verified mode
# ---------------------------------------------------------------------------


def test_e2e_client_claimed_rejected_at_aggregation_full_pipeline(
    monkeypatch,
    default_policy: ModelUpdatePolicy,
) -> None:
    """CLIENT_CLAIMED update submitted via full pipeline is rejected at the aggregation
    gate in coordinator_verified mode.

    The update goes through validate_incoming_update() (with schema from DB) in
    client_claimed mode, is approved (also in client_claimed mode), then aggregation
    is attempted after switching to coordinator_verified.  The aggregation service reads
    the trust mode from the env var and enforces the stricter provenance requirement.

    This exercises the full pipeline version of the CLIENT_CLAIMED rejection scenario —
    the DB-backed schema validation is exercised even for the rejected path.
    """
    monkeypatch.delenv(_ENV_VAR, raising=False)  # client_claimed for ingestion

    # No provider configured: resolve_sample_count() returns CLIENT_CLAIMED provenance.
    payload = _make_payload(weight_val=1.0)
    envelope = _register_key_and_make_envelope(
        payload,
        client_id="e2e-cc-client",
        update_id="e2e-cc-upd-001",
        sample_count=50,
        key_id="e2e-cc-key",
    )

    # Submit via full ingestion pipeline in client_claimed mode.
    result = validate_incoming_update(
        payload,
        envelope,
        policy=default_policy,
        trust_mode="client_claimed",
    )
    assert result["ingestion_status"] == "validated"
    assert result["schema_status"] == "verified"

    # Verify CLIENT_CLAIMED provenance persisted in the DB.
    record = get_update_record(client_id="e2e-cc-client", update_id="e2e-cc-upd-001")
    assert record.sample_count_provenance == PROVENANCE_CLIENT_CLAIMED

    # Approve in client_claimed mode (CLIENT_CLAIMED is accepted).
    approved = approve_update(
        client_id="e2e-cc-client",
        update_id="e2e-cc-upd-001",
        reason="client_claimed approval for rejection test",
    )
    assert approved.status == UpdateStatus.APPROVED

    # Switch to coordinator_verified mode — aggregation must reject.
    monkeypatch.setenv(_ENV_VAR, TRUST_MODE_COORDINATOR_VERIFIED)

    with pytest.raises(AggregationRejectedError):
        aggregate_approved_updates(
            [
                ApprovedUpdatePayload(
                    client_id="e2e-cc-client",
                    update_id="e2e-cc-upd-001",
                    model_version=_MODEL_VERSION,
                    round_number=_ROUND_NUMBER,
                    payload=payload,
                    sample_count=50,
                    sample_count_provenance=PROVENANCE_CLIENT_CLAIMED,
                )
            ],
            expected_state_dict=_SCHEMA_STATE_DICT,
            model_version=_MODEL_VERSION,
            round_number=_ROUND_NUMBER,
        )
