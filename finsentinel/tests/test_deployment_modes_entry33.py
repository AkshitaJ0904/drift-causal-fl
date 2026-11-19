"""Entry 33 — Explicit Sample-Count Trust Mode.

Covers all scenarios required by Entry 33:

1. client_claimed mode: backward-compatible; provider failure is non-fatal.
2. coordinator_verified mode: missing provider fails startup validation.
3. coordinator_verified mode: provider unavailable during ingestion → rejected.
4. coordinator_verified mode: coordinator selection failure → rejected.
5. coordinator_verified mode: count mismatch → rejected.
6. coordinator_verified mode: CLIENT_CLAIMED update rejected at approval.
7. coordinator_verified mode: CLIENT_CLAIMED update rejected at aggregation.
8. coordinator_verified mode: valid provider-verified update accepted end-to-end.
9. Invalid FINSENTINEL_SAMPLE_COUNT_TRUST_MODE value raises ValueError.
10. Existing client-claimed backward-compatibility preserved.

Design constraints
------------------
* Tests set FINSENTINEL_SAMPLE_COUNT_TRUST_MODE via monkeypatch and restore it.
* No PostgreSQL.  All DB operations use the SQLite StaticPool from conftest.py.
* StubCoordinatorAdapter / CoordinatorBackedSampleCountProvider are explicitly
  test doubles — not production providers.
* app.main startup validation is exercised by calling the extracted helper
  function directly, not by reimporting the module.
"""

from __future__ import annotations

import hashlib
import io

import numpy as np
import pytest
import torch

from aggregation.service import (
    AggregationRejectedError,
    ApprovedUpdatePayload,
    aggregate_approved_updates,
)
from coordination.coordinator_adapter import CoordinatorBackedSampleCountProvider
from coordination.stub_coordinator import StubCoordinatorAdapter
from core.config import (
    TRUST_MODE_CLIENT_CLAIMED,
    TRUST_MODE_COORDINATOR_VERIFIED,
    get_sample_count_trust_mode,
)
from enforcement.approval_service import (
    ApprovalError,
    UpdateStatus,
    approve_update,
    clear_approval_registry,
    record_ingestion_audit_result,
    register_validated_update,
)
from ingestion.sample_count_provider import (
    PROVENANCE_CLIENT_CLAIMED,
    PROVENANCE_PROVIDER_VERIFIED,
    SampleCountMismatchError,
    SampleCountResult,
    SampleCountVerificationError,
    resolve_sample_count,
)
from ingestion.service import configure_sample_count_provider

# ---------------------------------------------------------------------------
# Shared env-var key
# ---------------------------------------------------------------------------

_ENV_VAR = "FINSENTINEL_SAMPLE_COUNT_TRUST_MODE"


# ---------------------------------------------------------------------------
# Provider test doubles
# ---------------------------------------------------------------------------


class _MatchingProvider:
    name = "matching-stub"

    def __init__(self, count: int) -> None:
        self._count = count

    def get_verified_count(self, *, client_id, update_id, round_number) -> int | None:
        return self._count


class _NoneProvider:
    name = "none-stub"

    def get_verified_count(self, *, client_id, update_id, round_number) -> int | None:
        return None


class _RaisingProvider:
    name = "raising-stub"

    def get_verified_count(self, *, client_id, update_id, round_number) -> int | None:
        raise RuntimeError("coordinator unreachable")


class _MismatchProvider:
    name = "mismatch-stub"

    def get_verified_count(self, *, client_id, update_id, round_number) -> int | None:
        return 999  # always mismatches a client_claimed != 999


# ---------------------------------------------------------------------------
# Payload helper
# ---------------------------------------------------------------------------


def _make_npz_payload(shape: tuple[int, ...] = (3,)) -> bytes:
    buf = io.BytesIO()
    np.savez(buf, weight=np.ones(shape, dtype=np.float32))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. get_sample_count_trust_mode() — both modes and default
# ---------------------------------------------------------------------------


def test_default_trust_mode_is_client_claimed(monkeypatch):
    """When FINSENTINEL_SAMPLE_COUNT_TRUST_MODE is unset, mode is 'client_claimed'."""
    monkeypatch.delenv(_ENV_VAR, raising=False)
    assert get_sample_count_trust_mode() == TRUST_MODE_CLIENT_CLAIMED


def test_explicit_client_claimed(monkeypatch):
    monkeypatch.setenv(_ENV_VAR, TRUST_MODE_CLIENT_CLAIMED)
    assert get_sample_count_trust_mode() == TRUST_MODE_CLIENT_CLAIMED


def test_explicit_coordinator_verified(monkeypatch):
    monkeypatch.setenv(_ENV_VAR, TRUST_MODE_COORDINATOR_VERIFIED)
    assert get_sample_count_trust_mode() == TRUST_MODE_COORDINATOR_VERIFIED


def test_trust_mode_case_insensitive(monkeypatch):
    monkeypatch.setenv(_ENV_VAR, "Coordinator_Verified")
    assert get_sample_count_trust_mode() == TRUST_MODE_COORDINATOR_VERIFIED


def test_invalid_trust_mode_raises(monkeypatch):
    monkeypatch.setenv(_ENV_VAR, "unverified_chaos")
    with pytest.raises(ValueError, match="FINSENTINEL_SAMPLE_COUNT_TRUST_MODE"):
        get_sample_count_trust_mode()


# ---------------------------------------------------------------------------
# 2. Startup validation — coordinator_verified mode requires a provider
# ---------------------------------------------------------------------------


def test_startup_validation_no_provider_raises():
    """_validate_trust_mode_configuration raises when mode=coordinator_verified and
    no provider is configured."""
    from app.main import _validate_trust_mode_configuration

    configure_sample_count_provider(None)
    try:
        with pytest.raises(RuntimeError, match="coordinator_verified"):
            _validate_trust_mode_configuration(TRUST_MODE_COORDINATOR_VERIFIED)
    finally:
        configure_sample_count_provider(None)


def test_startup_validation_with_provider_passes():
    """_validate_trust_mode_configuration does not raise when a provider is configured."""
    from app.main import _validate_trust_mode_configuration

    configure_sample_count_provider(_MatchingProvider(100))
    try:
        _validate_trust_mode_configuration(TRUST_MODE_COORDINATOR_VERIFIED)
    finally:
        configure_sample_count_provider(None)


def test_startup_validation_client_claimed_no_provider_passes():
    """client_claimed mode never requires a provider at startup."""
    from app.main import _validate_trust_mode_configuration

    configure_sample_count_provider(None)
    _validate_trust_mode_configuration(TRUST_MODE_CLIENT_CLAIMED)


# ---------------------------------------------------------------------------
# 3. Provider unavailable during ingestion
# ---------------------------------------------------------------------------


def test_verified_mode_provider_unavailable_raises():
    """In coordinator_verified mode (require_verified=True), provider returning None raises."""
    with pytest.raises(SampleCountVerificationError):
        resolve_sample_count(
            client_claimed=50,
            provider=_NoneProvider(),
            client_id="cl-v1",
            update_id="upd-v1",
            round_number=1,
            require_verified=True,
        )


def test_client_claimed_mode_provider_unavailable_stores_client_claimed():
    """In client_claimed mode (require_verified=False), provider returning None → CLIENT_CLAIMED."""
    result = resolve_sample_count(
        client_claimed=75,
        provider=_NoneProvider(),
        client_id="cl-cc1",
        update_id="upd-cc1",
        round_number=1,
    )
    assert result.provenance == PROVENANCE_CLIENT_CLAIMED
    assert result.count == 75


# ---------------------------------------------------------------------------
# 4. Coordinator selection failure (provider raises)
# ---------------------------------------------------------------------------


def test_verified_mode_provider_raises_blocked():
    """In coordinator_verified mode, provider raising causes SampleCountVerificationError."""
    with pytest.raises(SampleCountVerificationError):
        resolve_sample_count(
            client_claimed=100,
            provider=_RaisingProvider(),
            client_id="cl-v2",
            update_id="upd-v2",
            round_number=1,
            require_verified=True,
        )


def test_client_claimed_mode_provider_raises_stores_client_claimed():
    """In client_claimed mode, provider raising falls back to CLIENT_CLAIMED."""
    result = resolve_sample_count(
        client_claimed=200,
        provider=_RaisingProvider(),
        client_id="cl-cc2",
        update_id="upd-cc2",
        round_number=1,
    )
    assert result.provenance == PROVENANCE_CLIENT_CLAIMED


# ---------------------------------------------------------------------------
# 5. Count mismatch — raises regardless of trust mode
# ---------------------------------------------------------------------------


def test_count_mismatch_raises_in_verified_mode():
    with pytest.raises(SampleCountMismatchError):
        resolve_sample_count(
            client_claimed=100,
            provider=_MismatchProvider(),
            client_id="cl-mm1",
            update_id="upd-mm1",
            round_number=1,
        )


def test_count_mismatch_raises_in_client_claimed_mode():
    """Mismatch always raises regardless of trust mode — the error is unambiguous."""
    result_or_raise = None
    try:
        result_or_raise = resolve_sample_count(
            client_claimed=100,
            provider=_MismatchProvider(),
            client_id="cl-mm2",
            update_id="upd-mm2",
            round_number=1,
        )
    except SampleCountMismatchError:
        result_or_raise = "raised"
    assert result_or_raise == "raised"


# ---------------------------------------------------------------------------
# 6. CLIENT_CLAIMED update rejected at approval in coordinator_verified mode
# ---------------------------------------------------------------------------


def test_client_claimed_rejected_at_approval_verified_mode(monkeypatch):
    """In coordinator_verified mode, approve_update() raises ApprovalError for
    CLIENT_CLAIMED records."""
    monkeypatch.setenv(_ENV_VAR, TRUST_MODE_COORDINATOR_VERIFIED)
    clear_approval_registry()
    try:
        sc = SampleCountResult(count=50, provenance=PROVENANCE_CLIENT_CLAIMED)
        register_validated_update(
            update_id="cc-upd-001",
            client_id="cc-client",
            model_version="cnn-v1",
            round_number=1,
            sample_count_result=sc,
            payload_sha256="b" * 64,
            risk_score=0,
            risk_severity="LOW",
            suspicious=False,
            anomaly_reasons=["none"],
            detector_version="v1",
            detector_config={"t": 0.5},
        )
        record_ingestion_audit_result(
            client_id="cc-client",
            update_id="cc-upd-001",
            audit_status="persisted",
            audit_failures=(),
        )
        with pytest.raises(ApprovalError, match="provider_verified"):
            approve_update(
                client_id="cc-client",
                update_id="cc-upd-001",
                reason="test approval",
            )
    finally:
        configure_sample_count_provider(None)
        clear_approval_registry()


def test_client_claimed_allowed_at_approval_in_client_claimed_mode(monkeypatch):
    """In client_claimed mode, approve_update() does not reject CLIENT_CLAIMED records."""
    monkeypatch.delenv(_ENV_VAR, raising=False)
    clear_approval_registry()
    try:
        sc = SampleCountResult(count=50, provenance=PROVENANCE_CLIENT_CLAIMED)
        register_validated_update(
            update_id="cc-upd-002",
            client_id="cc-client2",
            model_version="cnn-v1",
            round_number=1,
            sample_count_result=sc,
            payload_sha256="c" * 64,
            risk_score=0,
            risk_severity="LOW",
            suspicious=False,
            anomaly_reasons=["none"],
            detector_version="v1",
            detector_config={"t": 0.5},
        )
        record_ingestion_audit_result(
            client_id="cc-client2",
            update_id="cc-upd-002",
            audit_status="persisted",
            audit_failures=(),
        )
        record = approve_update(
            client_id="cc-client2",
            update_id="cc-upd-002",
            reason="approved in client_claimed mode",
        )
        assert record.status == UpdateStatus.APPROVED
    finally:
        clear_approval_registry()


# ---------------------------------------------------------------------------
# 7. CLIENT_CLAIMED update rejected at aggregation in coordinator_verified mode
# ---------------------------------------------------------------------------


def test_client_claimed_rejected_at_aggregation_verified_mode(monkeypatch):
    """In coordinator_verified mode, aggregate_approved_updates rejects CLIENT_CLAIMED records.

    The update is first approved in client_claimed mode (permitted), then
    aggregation is attempted in coordinator_verified mode — the aggregation
    service reads the trust mode from config and enforces the stricter check.
    """
    monkeypatch.delenv(_ENV_VAR, raising=False)  # client_claimed for registration
    clear_approval_registry()
    try:
        payload = _make_npz_payload()
        digest = hashlib.sha256(payload).hexdigest()

        sc = SampleCountResult(count=100, provenance=PROVENANCE_CLIENT_CLAIMED)
        register_validated_update(
            update_id="agg-cc-001",
            client_id="agg-cc-client",
            model_version="cnn-v1",
            round_number=1,
            sample_count_result=sc,
            payload_sha256=digest,
            risk_score=0,
            risk_severity="LOW",
            suspicious=False,
            anomaly_reasons=["none"],
            detector_version="v1",
            detector_config={"t": 0.5},
        )
        record_ingestion_audit_result(
            client_id="agg-cc-client",
            update_id="agg-cc-001",
            audit_status="persisted",
            audit_failures=(),
        )
        # Approve is allowed in client_claimed mode
        approve_update(
            client_id="agg-cc-client",
            update_id="agg-cc-001",
            reason="approved for aggregation rejection test",
        )

        # Switch to coordinator_verified — aggregation must reject
        monkeypatch.setenv(_ENV_VAR, TRUST_MODE_COORDINATOR_VERIFIED)
        expected = {"weight": torch.ones(3)}
        with pytest.raises(AggregationRejectedError):
            aggregate_approved_updates(
                [
                    ApprovedUpdatePayload(
                        client_id="agg-cc-client",
                        update_id="agg-cc-001",
                        model_version="cnn-v1",
                        round_number=1,
                        payload=payload,
                        sample_count=100,
                        sample_count_provenance=PROVENANCE_CLIENT_CLAIMED,
                    )
                ],
                expected_state_dict=expected,
                model_version="cnn-v1",
                round_number=1,
            )
    finally:
        clear_approval_registry()


# ---------------------------------------------------------------------------
# 8. Valid provider-verified update accepted through approval
# ---------------------------------------------------------------------------


def test_provider_verified_accepted_at_approval(monkeypatch):
    """In coordinator_verified mode, approve_update() accepts PROVIDER_VERIFIED records."""
    monkeypatch.setenv(_ENV_VAR, TRUST_MODE_COORDINATOR_VERIFIED)
    clear_approval_registry()
    try:
        sc = resolve_sample_count(
            client_claimed=100,
            provider=_MatchingProvider(100),
            client_id="pv-client",
            update_id="pv-upd-001",
            round_number=1,
        )
        assert sc.provenance == PROVENANCE_PROVIDER_VERIFIED

        register_validated_update(
            update_id="pv-upd-001",
            client_id="pv-client",
            model_version="cnn-v1",
            round_number=1,
            sample_count_result=sc,
            payload_sha256="d" * 64,
            risk_score=0,
            risk_severity="LOW",
            suspicious=False,
            anomaly_reasons=["none"],
            detector_version="v1",
            detector_config={"t": 0.5},
        )
        record_ingestion_audit_result(
            client_id="pv-client",
            update_id="pv-upd-001",
            audit_status="persisted",
            audit_failures=(),
        )

        record = approve_update(
            client_id="pv-client",
            update_id="pv-upd-001",
            reason="verified provenance approved",
        )
        assert record.status == UpdateStatus.APPROVED
        assert record.sample_count_provenance == PROVENANCE_PROVIDER_VERIFIED
    finally:
        configure_sample_count_provider(None)
        clear_approval_registry()


def test_provider_verified_is_approved_with_require_verified(monkeypatch):
    """is_approved with require_verified_provenance=True accepts PROVIDER_VERIFIED records."""
    from enforcement.approval_service import is_approved

    monkeypatch.delenv(_ENV_VAR, raising=False)
    clear_approval_registry()
    try:
        sc = resolve_sample_count(
            client_claimed=200,
            provider=_MatchingProvider(200),
            client_id="pv-client2",
            update_id="pv-upd-002",
            round_number=1,
        )
        assert sc.provenance == PROVENANCE_PROVIDER_VERIFIED

        sha = "e" * 64
        register_validated_update(
            update_id="pv-upd-002",
            client_id="pv-client2",
            model_version="cnn-v1",
            round_number=1,
            sample_count_result=sc,
            payload_sha256=sha,
            risk_score=0,
            risk_severity="LOW",
            suspicious=False,
            anomaly_reasons=["none"],
            detector_version="v1",
            detector_config={"t": 0.5},
        )
        record_ingestion_audit_result(
            client_id="pv-client2",
            update_id="pv-upd-002",
            audit_status="persisted",
            audit_failures=(),
        )
        approve_update(
            client_id="pv-client2",
            update_id="pv-upd-002",
            reason="approved in client_claimed mode for is_approved test",
        )

        assert is_approved(
            client_id="pv-client2",
            update_id="pv-upd-002",
            model_version="cnn-v1",
            round_number=1,
            payload_sha256=sha,
            sample_count=200,
            require_verified_provenance=True,
        )
    finally:
        clear_approval_registry()


def test_client_claimed_is_not_approved_with_require_verified(monkeypatch):
    """is_approved with require_verified_provenance=True rejects CLIENT_CLAIMED records."""
    from enforcement.approval_service import is_approved

    monkeypatch.delenv(_ENV_VAR, raising=False)
    clear_approval_registry()
    try:
        sc = SampleCountResult(count=150, provenance=PROVENANCE_CLIENT_CLAIMED)
        sha = "f" * 64
        register_validated_update(
            update_id="cc-is-003",
            client_id="cc-is-client",
            model_version="cnn-v1",
            round_number=1,
            sample_count_result=sc,
            payload_sha256=sha,
            risk_score=0,
            risk_severity="LOW",
            suspicious=False,
            anomaly_reasons=["none"],
            detector_version="v1",
            detector_config={"t": 0.5},
        )
        record_ingestion_audit_result(
            client_id="cc-is-client",
            update_id="cc-is-003",
            audit_status="persisted",
            audit_failures=(),
        )
        approve_update(
            client_id="cc-is-client",
            update_id="cc-is-003",
            reason="approved for is_approved test",
        )

        assert not is_approved(
            client_id="cc-is-client",
            update_id="cc-is-003",
            model_version="cnn-v1",
            round_number=1,
            payload_sha256=sha,
            sample_count=150,
            require_verified_provenance=True,
        )
    finally:
        clear_approval_registry()


# ---------------------------------------------------------------------------
# 9. StubCoordinatorAdapter path
# ---------------------------------------------------------------------------


def test_stub_coordinator_unselected_client_returns_none():
    """CoordinatorBackedSampleCountProvider returns None for a client not registered."""
    stub = StubCoordinatorAdapter()
    provider = CoordinatorBackedSampleCountProvider(stub)
    result = provider.get_verified_count(
        client_id="unknown-client",
        update_id="upd-x",
        round_number=1,
    )
    assert result is None


def test_stub_coordinator_wrong_round_returns_none():
    """CoordinatorBackedSampleCountProvider returns None for wrong round."""
    stub = StubCoordinatorAdapter()
    stub.register_participation(
        client_id="cl-round2",
        round_number=2,
        sample_count=50,
        update_id="upd-round2",
    )
    provider = CoordinatorBackedSampleCountProvider(stub)
    result = provider.get_verified_count(
        client_id="cl-round2",
        update_id="upd-round2",
        round_number=1,
    )
    assert result is None


def test_stub_coordinator_selected_client_returns_verified_count():
    """CoordinatorBackedSampleCountProvider returns the registered count.

    Uses a round-level registration (no update_id) so is_client_selected()
    returns True for any update from this client in this round.
    """
    stub = StubCoordinatorAdapter()
    stub.register_participation(
        client_id="cl-selected",
        round_number=1,
        sample_count=200,
        # no update_id: round-level registration, matches any update_id
    )
    provider = CoordinatorBackedSampleCountProvider(stub)
    result = provider.get_verified_count(
        client_id="cl-selected",
        update_id="upd-selected",
        round_number=1,
    )
    assert result == 200


def test_stub_coordinator_verified_mode_unselected_raises():
    """In coordinator_verified mode (require_verified=True), unselected client raises."""
    stub = StubCoordinatorAdapter()
    provider = CoordinatorBackedSampleCountProvider(stub)
    with pytest.raises(SampleCountVerificationError):
        resolve_sample_count(
            client_claimed=100,
            provider=provider,
            client_id="cl-unselected",
            update_id="upd-unselected",
            round_number=1,
            require_verified=True,
        )


# ---------------------------------------------------------------------------
# 10. Backward compatibility: existing client_claimed behaviour preserved
# ---------------------------------------------------------------------------


def test_backward_compat_no_provider_stores_client_claimed(monkeypatch):
    """No provider + no env var → CLIENT_CLAIMED (Entry 32 compat)."""
    monkeypatch.delenv(_ENV_VAR, raising=False)
    result = resolve_sample_count(
        client_claimed=300,
        provider=None,
        client_id="cl-compat1",
        update_id="upd-compat1",
        round_number=1,
    )
    assert result.provenance == PROVENANCE_CLIENT_CLAIMED
    assert result.count == 300


def test_backward_compat_matching_provider_produces_verified(monkeypatch):
    """Matching provider + no env var → PROVIDER_VERIFIED (Entry 32 compat)."""
    monkeypatch.delenv(_ENV_VAR, raising=False)
    result = resolve_sample_count(
        client_claimed=400,
        provider=_MatchingProvider(400),
        client_id="cl-compat2",
        update_id="upd-compat2",
        round_number=1,
    )
    assert result.provenance == PROVENANCE_PROVIDER_VERIFIED
    assert result.count == 400


def test_configure_sample_count_provider_persists():
    """configure_sample_count_provider() sets the module-level provider."""
    from ingestion import service as _svc

    configure_sample_count_provider(_MatchingProvider(50))
    try:
        assert _svc._sample_count_provider is not None
    finally:
        configure_sample_count_provider(None)
        assert _svc._sample_count_provider is None
