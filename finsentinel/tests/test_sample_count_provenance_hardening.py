"""Regression tests for the Sample Count Provenance Security Hardening (Entry 28).

Verifies:
 Q2 — Internal provenance bypass closed: registration requires SampleCountResult;
       free-string provenance values are rejected at construction time.
 Q4 — Coordinator client-selection gating: CoordinatorBackedSampleCountProvider
       calls is_client_selected before accepting an expected count.

Ten scenarios tested:
 1. Forged provenance string → SampleCountResult raises ValueError at construction.
 2. SampleCountResult with invalid count → ValueError at construction.
 3. Provider result with invalid count (mismatched) → SampleCountMismatchError.
 4. Unselected client → get_verified_count returns None (Q4 fix).
 5. Coordinator unavailable (is_client_selected returns None) → get_verified_count
    returns None.
 6. Wrong round → get_verified_count returns None (not selected for that round).
 7. Approval with client-claimed count under verified-only policy → is_approved
    returns False when require_verified_provenance=True.
 8. Aggregation with provenance mismatch under verified-only policy →
    AggregationRejectedError.
 9. Valid verified-provider path → registration succeeds, provenance stored.
10. Existing client-claimed path where policy allows → registration and approval
    succeed as before.
"""

from __future__ import annotations

import hashlib

import pytest

from aggregation.service import (
    AggregationRejectedError,
    ApprovedUpdatePayload,
    aggregate_approved_updates,
)
from coordination.coordinator_adapter import CoordinatorBackedSampleCountProvider
from coordination.stub_coordinator import StubCoordinatorAdapter
from enforcement.approval_service import (
    approve_update,
    clear_approval_registry,
    get_update_record,
    is_approved,
    record_ingestion_audit_result,
    register_validated_update,
)
from ingestion.sample_count_provider import (
    PROVENANCE_CLIENT_CLAIMED,
    PROVENANCE_PROVIDER_VERIFIED,
    SampleCountMismatchError,
    SampleCountResult,
    resolve_sample_count,
)

TEST_DIGEST = "d" * 64


@pytest.fixture(autouse=True)
def reset_approval_registry():
    clear_approval_registry()
    yield
    clear_approval_registry()


# ---------------------------------------------------------------------------
# Scenario 1 — Forged provenance string rejected at SampleCountResult construction
# ---------------------------------------------------------------------------

def test_forged_provenance_string_rejected_at_construction() -> None:
    """SampleCountResult.__post_init__ blocks any provenance not in _VALID_PROVENANCES.

    An adversary cannot construct a SampleCountResult with an arbitrary string
    to bypass downstream provenance checks — the dataclass itself fails closed.
    """
    with pytest.raises(ValueError, match="provenance"):
        SampleCountResult(count=100, provenance="attacker_controlled")

    with pytest.raises(ValueError, match="provenance"):
        SampleCountResult(count=100, provenance="provider_verified_forged")

    with pytest.raises(ValueError, match="provenance"):
        SampleCountResult(count=100, provenance="")


# ---------------------------------------------------------------------------
# Scenario 2 — SampleCountResult with invalid count rejected at construction
# ---------------------------------------------------------------------------

def test_invalid_count_rejected_at_construction() -> None:
    """SampleCountResult.__post_init__ requires a positive integer count."""
    with pytest.raises(ValueError, match="count"):
        SampleCountResult(count=0, provenance=PROVENANCE_CLIENT_CLAIMED)

    with pytest.raises(ValueError, match="count"):
        SampleCountResult(count=-1, provenance=PROVENANCE_CLIENT_CLAIMED)

    with pytest.raises(ValueError, match="count"):
        SampleCountResult(count=True, provenance=PROVENANCE_CLIENT_CLAIMED)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Scenario 3 — Provider returning mismatched count raises SampleCountMismatchError
# ---------------------------------------------------------------------------

def test_provider_mismatched_count_raises_mismatch_error() -> None:
    """When a provider returns a count that differs from the client's claim,
    resolve_sample_count raises SampleCountMismatchError.  The update must be
    rejected — a mismatch indicates either a dishonest client or a misconfigured
    provider.
    """

    class _MismatchProvider:
        name = "mismatch-test"

        def get_verified_count(self, *, client_id, update_id, round_number):
            return 999  # always returns a different value

    with pytest.raises(SampleCountMismatchError):
        resolve_sample_count(
            client_claimed=100,
            provider=_MismatchProvider(),
            client_id="c-1",
            update_id="u-1",
            round_number=1,
        )


# ---------------------------------------------------------------------------
# Scenario 4 — Unselected client → provider returns None (Q4 fix)
# ---------------------------------------------------------------------------

def test_unselected_client_returns_none_from_coordinator_provider() -> None:
    """CoordinatorBackedSampleCountProvider must return None when is_client_selected
    returns False — the client was not invited to this round.

    The fix closes Q4: without client-selection gating, any client could supply
    an update_id that happens to match a coordinator record and obtain a trusted
    expected count for a round they were not selected for.
    """
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="selected-client", round_number=1, sample_count=50)
    # "unselected-client" has no participation record → not selected
    provider = CoordinatorBackedSampleCountProvider(adapter=stub)

    result = provider.get_verified_count(
        client_id="unselected-client",
        update_id="upd-xyz",
        round_number=1,
    )
    assert result is None, (
        "get_verified_count must return None for a client with no participation record"
    )


# ---------------------------------------------------------------------------
# Scenario 5 — Coordinator unavailable (is_client_selected returns None)
# ---------------------------------------------------------------------------

def test_coordinator_unavailable_returns_none() -> None:
    """When is_client_selected returns None (coordinator unreachable or unknown),
    CoordinatorBackedSampleCountProvider must return None — not substitute a
    fabricated or cached trusted count.

    This ensures that coordinator unavailability is treated as a verification
    failure, not an implicit pass.
    """

    class _UnavailableCoordinator:
        name = "unavailable"

        def is_client_selected(self, *, client_id, round_number):
            return None  # unknown / coordinator unreachable

        def get_expected_sample_count(self, *, client_id, update_id, round_number):
            raise AssertionError(
                "get_expected_sample_count must not be called when is_client_selected is None"
            )

    provider = CoordinatorBackedSampleCountProvider(adapter=_UnavailableCoordinator())
    result = provider.get_verified_count(
        client_id="any-client",
        update_id="any-update",
        round_number=1,
    )
    assert result is None


# ---------------------------------------------------------------------------
# Scenario 6 — Wrong round → provider returns None
# ---------------------------------------------------------------------------

def test_wrong_round_returns_none_from_coordinator_provider() -> None:
    """A client selected for round 1 must not receive a trusted count for round 2.

    StubCoordinatorAdapter tracks participation per (client_id, round_number).
    A request for a round the client was not selected for returns None.
    """
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-rnd", round_number=1, sample_count=42)
    provider = CoordinatorBackedSampleCountProvider(adapter=stub)

    result = provider.get_verified_count(
        client_id="cl-rnd",
        update_id="upd-rnd",
        round_number=2,  # client was selected for round 1, not 2
    )
    assert result is None, (
        "Provider must return None for a round the client was not selected for"
    )


# ---------------------------------------------------------------------------
# Scenario 7 — Approval with client-claimed count under verified-only policy
# ---------------------------------------------------------------------------

def test_client_claimed_count_blocked_by_verified_only_policy() -> None:
    """When require_verified_provenance=True, is_approved() must return False
    for an update whose count has CLIENT_CLAIMED provenance, even if every
    other approval field matches exactly.

    This enforces the verified-only policy at the approval gate: an operator
    who requires verified counts cannot be bypassed by a client that never
    had its count independently verified.
    """
    register_validated_update(
        update_id="prov-policy-01",
        client_id="c-policy",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=10, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="hardening-test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
    )
    record_ingestion_audit_result(
        client_id="c-policy",
        update_id="prov-policy-01",
        audit_status="persisted",
        audit_failures=(),
    )
    approve_update(
        client_id="c-policy",
        update_id="prov-policy-01",
        reason="Approved for provenance policy test.",
    )

    # Without verified-only requirement: approved.
    assert is_approved(
        client_id="c-policy",
        update_id="prov-policy-01",
        model_version="cnn-v1",
        round_number=1,
        sample_count=10,
        payload_sha256=TEST_DIGEST,
    )

    # With verified-only requirement: rejected because provenance is CLIENT_CLAIMED.
    assert not is_approved(
        client_id="c-policy",
        update_id="prov-policy-01",
        model_version="cnn-v1",
        round_number=1,
        sample_count=10,
        payload_sha256=TEST_DIGEST,
        require_verified_provenance=True,
    )


# ---------------------------------------------------------------------------
# Scenario 8 — Aggregation with client-claimed count under verified-only policy
# ---------------------------------------------------------------------------

def test_aggregation_rejects_client_claimed_under_verified_only_policy() -> None:
    """aggregate_approved_updates with require_verified_provenance=True must raise
    AggregationRejectedError for an update with CLIENT_CLAIMED provenance.

    The aggregation service propagates the require_verified_provenance flag to
    is_approved(), which filters out client-claimed rows.
    """
    import torch

    from ingestion.serialization import serialize_state_dict

    state_dict = {
        "layer.weight": torch.tensor([[1.0, 1.0]], dtype=torch.float32),
        "layer.bias": torch.tensor([0.5], dtype=torch.float32),
    }
    payload = serialize_state_dict(state_dict)
    digest = hashlib.sha256(payload).hexdigest()

    register_validated_update(
        update_id="prov-agg-01",
        client_id="c-agg",
        sample_count_result=SampleCountResult(count=5, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=digest,
        model_version="cnn-v1",
        round_number=1,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="hardening-test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
    )
    record_ingestion_audit_result(
        client_id="c-agg",
        update_id="prov-agg-01",
        audit_status="persisted",
        audit_failures=(),
    )
    approve_update(
        client_id="c-agg",
        update_id="prov-agg-01",
        reason="Approved for aggregation provenance mismatch test.",
    )

    with pytest.raises(AggregationRejectedError, match="not approved"):
        aggregate_approved_updates(
            [
                ApprovedUpdatePayload(
                    client_id="c-agg",
                    update_id="prov-agg-01",
                    model_version="cnn-v1",
                    round_number=1,
                    payload=payload,
                    sample_count=5,
                )
            ],
            expected_state_dict=state_dict,
            model_version="cnn-v1",
            round_number=1,
            require_verified_provenance=True,
        )


# ---------------------------------------------------------------------------
# Scenario 9 — Valid verified-provider path succeeds end-to-end
# ---------------------------------------------------------------------------

def test_verified_provider_path_succeeds() -> None:
    """When a provider successfully verifies the count, registration stores
    PROVENANCE_PROVIDER_VERIFIED and the update can be approved and aggregated.

    This is the happy path for the new hardening: a client with a legitimately
    verified count flows through without obstruction.
    """
    import torch

    from ingestion.serialization import serialize_state_dict

    state_dict = {
        "layer.weight": torch.tensor([[2.0, 2.0]], dtype=torch.float32),
        "layer.bias": torch.tensor([1.0], dtype=torch.float32),
    }
    payload = serialize_state_dict(state_dict)
    digest = hashlib.sha256(payload).hexdigest()

    # Simulate a verified result via resolve_sample_count with a matching provider.
    class _MatchingProvider:
        name = "matching-test"

        def get_verified_count(self, *, client_id, update_id, round_number):
            return 20

    sc_result = resolve_sample_count(
        client_claimed=20,
        provider=_MatchingProvider(),
        client_id="c-verified",
        update_id="upd-verified-01",
        round_number=1,
    )
    assert sc_result.provenance == PROVENANCE_PROVIDER_VERIFIED

    register_validated_update(
        update_id="upd-verified-01",
        client_id="c-verified",
        sample_count_result=sc_result,
        payload_sha256=digest,
        model_version="cnn-v1",
        round_number=1,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="hardening-test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
    )
    record_ingestion_audit_result(
        client_id="c-verified",
        update_id="upd-verified-01",
        audit_status="persisted",
        audit_failures=(),
    )
    approve_update(
        client_id="c-verified",
        update_id="upd-verified-01",
        reason="Verified-provider path test approval.",
    )

    record = get_update_record(client_id="c-verified", update_id="upd-verified-01")
    assert record.sample_count == 20
    assert record.sample_count_provenance == PROVENANCE_PROVIDER_VERIFIED

    # Must pass the verified-only policy gate.
    assert is_approved(
        client_id="c-verified",
        update_id="upd-verified-01",
        model_version="cnn-v1",
        round_number=1,
        sample_count=20,
        payload_sha256=digest,
        require_verified_provenance=True,
    )

    # Must also succeed in aggregation under verified-only policy.
    result = aggregate_approved_updates(
        [
            ApprovedUpdatePayload(
                client_id="c-verified",
                update_id="upd-verified-01",
                model_version="cnn-v1",
                round_number=1,
                payload=payload,
                sample_count=20,
            )
        ],
        expected_state_dict=state_dict,
        model_version="cnn-v1",
        round_number=1,
        require_verified_provenance=True,
    )
    import torch as _torch
    assert _torch.allclose(result["layer.weight"], state_dict["layer.weight"])


# ---------------------------------------------------------------------------
# Scenario 10 — Existing client-claimed path still works where policy allows
# ---------------------------------------------------------------------------

def test_client_claimed_path_succeeds_without_verified_policy() -> None:
    """The existing client-claimed workflow must continue to work when the
    verified-only policy is NOT required.

    Hardening is additive: existing clients using CLIENT_CLAIMED provenance
    are not broken — only stricter policies block them.
    """
    import torch

    from ingestion.serialization import serialize_state_dict

    state_dict = {
        "layer.weight": torch.tensor([[0.5, 0.5]], dtype=torch.float32),
        "layer.bias": torch.tensor([0.0], dtype=torch.float32),
    }
    payload = serialize_state_dict(state_dict)
    digest = hashlib.sha256(payload).hexdigest()

    register_validated_update(
        update_id="upd-claimed-01",
        client_id="c-claimed",
        sample_count_result=SampleCountResult(count=8, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=digest,
        model_version="cnn-v1",
        round_number=1,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="hardening-test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
    )
    record_ingestion_audit_result(
        client_id="c-claimed",
        update_id="upd-claimed-01",
        audit_status="persisted",
        audit_failures=(),
    )
    approve_update(
        client_id="c-claimed",
        update_id="upd-claimed-01",
        reason="Client-claimed path backward compatibility test.",
    )

    record = get_update_record(client_id="c-claimed", update_id="upd-claimed-01")
    assert record.sample_count == 8
    assert record.sample_count_provenance == PROVENANCE_CLIENT_CLAIMED

    # Without require_verified_provenance, the update is approved.
    assert is_approved(
        client_id="c-claimed",
        update_id="upd-claimed-01",
        model_version="cnn-v1",
        round_number=1,
        sample_count=8,
        payload_sha256=digest,
    )

    result = aggregate_approved_updates(
        [
            ApprovedUpdatePayload(
                client_id="c-claimed",
                update_id="upd-claimed-01",
                model_version="cnn-v1",
                round_number=1,
                payload=payload,
                sample_count=8,
            )
        ],
        expected_state_dict=state_dict,
        model_version="cnn-v1",
        round_number=1,
    )
    import torch as _torch
    assert _torch.allclose(result["layer.weight"], state_dict["layer.weight"])
