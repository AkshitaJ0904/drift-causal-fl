"""Adversarial bypass test for Entry 31 audit.

Documents the actual security guarantees of _ProviderVerifiedSeal after the
Entry 31 fix (identity check replacing isinstance).

After the fix:
- Bypass 1 (direct import of _PROVIDER_VERIFIED_SEAL singleton) REMAINS possible.
  Python provides no way to prevent importing a module-level name at runtime.
  Code-review discipline is the only practical control.
- Bypass 2 (constructing a new _ProviderVerifiedSeal() instance) is NOW CLOSED
  by the identity check (self._seal is not _PROVIDER_VERIFIED_SEAL).

These tests document what Python CAN and CANNOT prevent at runtime.
"""

from __future__ import annotations

import pytest

# --- Direct imports of the private sentinel ---
from ingestion.sample_count_provider import (
    _PROVIDER_VERIFIED_SEAL,  # noqa: PLC2701  direct import of private name
    PROVENANCE_PROVIDER_VERIFIED,
    SampleCountResult,
    _ProviderVerifiedSeal,  # noqa: PLC2701  direct import of private class
)

# ---------------------------------------------------------------------------
# Bypass 1 (REMAINS): import the singleton and pass it directly
# ---------------------------------------------------------------------------


def test_bypass_via_direct_import_of_singleton() -> None:
    """Direct import of _PROVIDER_VERIFIED_SEAL still bypasses the check.

    This is a Python limitation: identity-based checks cannot prevent a
    caller that explicitly imports the private singleton.  The control
    is code-review discipline (private name, underscore prefix).
    """
    result = SampleCountResult(
        count=100,
        provenance=PROVENANCE_PROVIDER_VERIFIED,
        _seal=_PROVIDER_VERIFIED_SEAL,
    )
    assert result.provenance == PROVENANCE_PROVIDER_VERIFIED
    assert result.count == 100


# ---------------------------------------------------------------------------
# Bypass 2 (FIXED): a fresh _ProviderVerifiedSeal() instance is now rejected
# ---------------------------------------------------------------------------


def test_new_instance_of_seal_class_now_rejected() -> None:
    """After the identity-check fix, a freshly created _ProviderVerifiedSeal() is rejected.

    Only the specific _PROVIDER_VERIFIED_SEAL singleton passes.
    """
    my_own_seal = _ProviderVerifiedSeal()
    with pytest.raises(ValueError, match="resolve_sample_count"):
        SampleCountResult(
            count=50,
            provenance=PROVENANCE_PROVIDER_VERIFIED,
            _seal=my_own_seal,
        )


# ---------------------------------------------------------------------------
# Confirm direct-import bypass still accepted by the registration API
# ---------------------------------------------------------------------------


def test_direct_import_bypass_accepted_by_registration_api() -> None:
    """The registration path accepts a result built with the imported singleton.

    Documents the remaining bypass surface: an internal caller that explicitly
    imports _PROVIDER_VERIFIED_SEAL can forge provider_verified provenance
    without calling resolve_sample_count().  The control is code review only.
    """
    from enforcement.approval_service import (
        clear_approval_registry,
        get_update_record,
        record_ingestion_audit_result,
        register_validated_update,
    )

    forged = SampleCountResult(
        count=200,
        provenance=PROVENANCE_PROVIDER_VERIFIED,
        _seal=_PROVIDER_VERIFIED_SEAL,
    )
    clear_approval_registry()
    register_validated_update(
        update_id="bypass-001",
        client_id="attacker-client",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=forged,
        payload_sha256="c" * 64,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=["none"],
        detector_version="v1",
        detector_config={"t": 0.5},
    )
    record_ingestion_audit_result(
        client_id="attacker-client",
        update_id="bypass-001",
        audit_status="persisted",
        audit_failures=(),
    )
    record = get_update_record(client_id="attacker-client", update_id="bypass-001")
    assert record.sample_count_provenance == PROVENANCE_PROVIDER_VERIFIED
    clear_approval_registry()


# ---------------------------------------------------------------------------
# What the guard correctly prevents (no seal at all, wrong type)
# ---------------------------------------------------------------------------


def test_no_seal_raises() -> None:
    """Without a seal the check rejects direct construction."""
    with pytest.raises(ValueError, match="resolve_sample_count"):
        SampleCountResult(count=100, provenance=PROVENANCE_PROVIDER_VERIFIED)


def test_wrong_type_seal_raises() -> None:
    """A non-singleton object is rejected."""
    with pytest.raises(ValueError, match="resolve_sample_count"):
        SampleCountResult(
            count=100,
            provenance=PROVENANCE_PROVIDER_VERIFIED,
            _seal=object(),  # type: ignore[arg-type]
        )
