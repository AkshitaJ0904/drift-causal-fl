"""Tests for the trusted sample-count provider interface.

Coverage:
 - NullSampleCountProvider always returns None
 - resolve_sample_count with provider=None → CLIENT_CLAIMED
 - resolve_sample_count with provider returning matching count → PROVIDER_VERIFIED
 - resolve_sample_count with provider returning mismatched count → SampleCountMismatchError
 - resolve_sample_count with provider returning None → CLIENT_CLAIMED
 - resolve_sample_count with provider raising → CLIENT_CLAIMED (unless require_verified)
 - resolve_sample_count with provider returning invalid value → SampleCountMismatchError
 - require_verified=True + no provider → SampleCountVerificationError
 - require_verified=True + provider returning None → SampleCountVerificationError
 - require_verified=True + provider raising → SampleCountVerificationError
 - client_claimed <= 0 or non-int → ValueError
 - SampleCountProvider is a Protocol (structural subtyping)
 - Provenance values stored in UpdateApproval after register_validated_update
 - Ingestion service: provider success → provenance bound to approval record
 - Ingestion service: provider mismatch → UpdatePolicyRejectedError
 - Ingestion service: require_verified, no provider → UpdatePolicyRejectedError
"""

from __future__ import annotations

from typing import TypedDict

import pytest

from ingestion.sample_count_provider import (
    PROVENANCE_CLIENT_CLAIMED,
    PROVENANCE_PROVIDER_VERIFIED,
    NullSampleCountProvider,
    SampleCountMismatchError,
    SampleCountProvider,
    SampleCountResult,
    SampleCountVerificationError,
    resolve_sample_count,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _IdentityKwargs(TypedDict):
    client_id: str
    update_id: str
    round_number: int

_IDENTITY: _IdentityKwargs = {"client_id": "c-1", "update_id": "u-1", "round_number": 1}


class _FixedProvider:
    """Test provider that returns a fixed count or None."""

    name = "test-fixed"

    def __init__(self, count: int | None = None, raise_exc: Exception | None = None):
        self._count = count
        self._raise = raise_exc

    def get_verified_count(self, *, client_id, update_id, round_number) -> int | None:
        if self._raise is not None:
            raise self._raise
        return self._count


# ---------------------------------------------------------------------------
# NullSampleCountProvider
# ---------------------------------------------------------------------------


def test_null_provider_always_returns_none() -> None:
    p = NullSampleCountProvider()
    assert p.get_verified_count(client_id="c", update_id="u", round_number=1) is None


def test_null_provider_name() -> None:
    assert NullSampleCountProvider().name == "null"


# ---------------------------------------------------------------------------
# Protocol structural subtyping
# ---------------------------------------------------------------------------


def test_null_provider_satisfies_protocol() -> None:
    assert isinstance(NullSampleCountProvider(), SampleCountProvider)


def test_fixed_provider_satisfies_protocol() -> None:
    assert isinstance(_FixedProvider(count=42), SampleCountProvider)


# ---------------------------------------------------------------------------
# resolve_sample_count — no provider
# ---------------------------------------------------------------------------


def test_no_provider_returns_client_claimed() -> None:
    result = resolve_sample_count(client_claimed=100, provider=None, **_IDENTITY)
    assert result.count == 100
    assert result.provenance == PROVENANCE_CLIENT_CLAIMED
    assert result.provider_name is None


def test_no_provider_require_verified_raises() -> None:
    with pytest.raises(SampleCountVerificationError, match="no provider"):
        resolve_sample_count(
            client_claimed=100,
            provider=None,
            require_verified=True,
            **_IDENTITY,
        )


# ---------------------------------------------------------------------------
# resolve_sample_count — provider returns matching count
# ---------------------------------------------------------------------------


def test_provider_match_returns_verified() -> None:
    result = resolve_sample_count(
        client_claimed=200,
        provider=_FixedProvider(count=200),
        **_IDENTITY,
    )
    assert result.count == 200
    assert result.provenance == PROVENANCE_PROVIDER_VERIFIED
    assert result.provider_name == "test-fixed"


def test_provider_match_require_verified_returns_verified() -> None:
    result = resolve_sample_count(
        client_claimed=50,
        provider=_FixedProvider(count=50),
        require_verified=True,
        **_IDENTITY,
    )
    assert result.provenance == PROVENANCE_PROVIDER_VERIFIED


# ---------------------------------------------------------------------------
# resolve_sample_count — provider returns mismatched count
# ---------------------------------------------------------------------------


def test_provider_mismatch_raises() -> None:
    with pytest.raises(SampleCountMismatchError, match="300"):
        resolve_sample_count(
            client_claimed=200,
            provider=_FixedProvider(count=300),
            **_IDENTITY,
        )


def test_provider_mismatch_contains_provider_name() -> None:
    with pytest.raises(SampleCountMismatchError, match="test-fixed"):
        resolve_sample_count(
            client_claimed=10,
            provider=_FixedProvider(count=11),
            **_IDENTITY,
        )


# ---------------------------------------------------------------------------
# resolve_sample_count — provider returns None (unavailable)
# ---------------------------------------------------------------------------


def test_provider_none_result_falls_back_to_client_claimed() -> None:
    result = resolve_sample_count(
        client_claimed=77,
        provider=_FixedProvider(count=None),
        **_IDENTITY,
    )
    assert result.count == 77
    assert result.provenance == PROVENANCE_CLIENT_CLAIMED


def test_provider_none_result_require_verified_raises() -> None:
    with pytest.raises(SampleCountVerificationError, match="could not verify"):
        resolve_sample_count(
            client_claimed=77,
            provider=_FixedProvider(count=None),
            require_verified=True,
            **_IDENTITY,
        )


# ---------------------------------------------------------------------------
# resolve_sample_count — provider raises
# ---------------------------------------------------------------------------


def test_provider_exception_falls_back_to_client_claimed() -> None:
    result = resolve_sample_count(
        client_claimed=55,
        provider=_FixedProvider(raise_exc=RuntimeError("network down")),
        **_IDENTITY,
    )
    assert result.provenance == PROVENANCE_CLIENT_CLAIMED
    assert result.count == 55


def test_provider_exception_require_verified_raises() -> None:
    with pytest.raises(SampleCountVerificationError, match="raised an error"):
        resolve_sample_count(
            client_claimed=55,
            provider=_FixedProvider(raise_exc=RuntimeError("network down")),
            require_verified=True,
            **_IDENTITY,
        )


# ---------------------------------------------------------------------------
# resolve_sample_count — provider returns invalid value
# ---------------------------------------------------------------------------


def test_provider_zero_count_raises_mismatch() -> None:
    with pytest.raises(SampleCountMismatchError, match="invalid count"):
        resolve_sample_count(
            client_claimed=10,
            provider=_FixedProvider(count=0),
            **_IDENTITY,
        )


def test_provider_negative_count_raises_mismatch() -> None:
    with pytest.raises(SampleCountMismatchError, match="invalid count"):
        resolve_sample_count(
            client_claimed=10,
            provider=_FixedProvider(count=-5),
            **_IDENTITY,
        )


# ---------------------------------------------------------------------------
# resolve_sample_count — invalid client_claimed
# ---------------------------------------------------------------------------


def test_zero_client_claimed_raises() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        resolve_sample_count(client_claimed=0, provider=None, **_IDENTITY)


def test_negative_client_claimed_raises() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        resolve_sample_count(client_claimed=-1, provider=None, **_IDENTITY)


def test_bool_client_claimed_raises() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        resolve_sample_count(client_claimed=True, provider=None, **_IDENTITY)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SampleCountResult fields
# ---------------------------------------------------------------------------


def test_result_fields_are_frozen() -> None:
    r = SampleCountResult(count=10, provenance=PROVENANCE_CLIENT_CLAIMED)
    with pytest.raises((AttributeError, TypeError)):
        r.count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# UpdateApproval provenance storage
# ---------------------------------------------------------------------------


def test_register_validated_update_stores_provenance() -> None:
    from enforcement.approval_service import (
        clear_approval_registry,
        get_update_record,
        record_ingestion_audit_result,
        register_validated_update,
    )

    clear_approval_registry()
    register_validated_update(
        update_id="prov-001",
        client_id="prov-client",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=resolve_sample_count(
            client_claimed=100,
            provider=_FixedProvider(count=100),
            client_id="prov-client",
            update_id="prov-001",
            round_number=1,
        ),
        payload_sha256="a" * 64,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=["none"],
        detector_version="v1",
        detector_config={"t": 0.5},
    )
    record_ingestion_audit_result(
        client_id="prov-client",
        update_id="prov-001",
        audit_status="persisted",
        audit_failures=(),
    )
    record = get_update_record(client_id="prov-client", update_id="prov-001")
    assert record.sample_count_provenance == PROVENANCE_PROVIDER_VERIFIED
    clear_approval_registry()


def test_register_validated_update_default_provenance_is_client_claimed() -> None:
    from enforcement.approval_service import (
        clear_approval_registry,
        get_update_record,
        record_ingestion_audit_result,
        register_validated_update,
    )

    clear_approval_registry()
    register_validated_update(
        update_id="prov-002",
        client_id="prov-client",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=50, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256="b" * 64,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=["none"],
        detector_version="v1",
        detector_config={"t": 0.5},
    )
    record_ingestion_audit_result(
        client_id="prov-client",
        update_id="prov-002",
        audit_status="persisted",
        audit_failures=(),
    )
    record = get_update_record(client_id="prov-client", update_id="prov-002")
    assert record.sample_count_provenance == PROVENANCE_CLIENT_CLAIMED
    clear_approval_registry()


def test_sample_count_result_invalid_provenance_raises() -> None:
    with pytest.raises(ValueError, match="provenance"):
        SampleCountResult(count=50, provenance="unknown_provenance")
