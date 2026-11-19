"""Adversarial regression tests for Entry 30: Sample Count Provenance Hardening.

Findings covered
----------------
A1 — Design weakness (now fixed):
    Direct construction of SampleCountResult with provenance='provider_verified'
    no longer succeeds.  The _ProviderVerifiedSeal sentinel is required and may
    only be supplied by resolve_sample_count().

B2 — Stub documentation/behavior gap (now fixed):
    StubCoordinatorAdapter.is_client_selected() now returns False for known
    clients queried for a round they are not registered for, matching the
    documented contract.  The selected==False branch of
    CoordinatorBackedSampleCountProvider.get_verified_count() is now
    exercisable in tests.
"""

from __future__ import annotations

from typing import TypedDict

import pytest

from coordination.coordinator_adapter import CoordinatorBackedSampleCountProvider
from coordination.stub_coordinator import StubCoordinatorAdapter
from ingestion.sample_count_provider import (
    PROVENANCE_CLIENT_CLAIMED,
    PROVENANCE_PROVIDER_VERIFIED,
    SampleCountResult,
    resolve_sample_count,
)


class _IdentityKwargs(TypedDict):
    client_id: str
    update_id: str
    round_number: int


_IDENTITY: _IdentityKwargs = {"client_id": "a-client", "update_id": "upd-001", "round_number": 1}


class _FixedProvider:
    name = "fixed"

    def __init__(self, count: int) -> None:
        self._count = count

    def get_verified_count(self, *, client_id, update_id, round_number) -> int:
        return self._count


# ---------------------------------------------------------------------------
# Finding A1 — provenance forgeability
# ---------------------------------------------------------------------------


def test_provider_verified_provenance_cannot_be_directly_forged() -> None:
    """SampleCountResult(provenance='provider_verified') without the seal raises."""
    with pytest.raises(ValueError, match="resolve_sample_count"):
        SampleCountResult(count=100, provenance=PROVENANCE_PROVIDER_VERIFIED)


def test_provider_verified_provenance_cannot_be_forged_with_provider_name() -> None:
    """The seal check fires even when provider_name is supplied."""
    with pytest.raises(ValueError, match="resolve_sample_count"):
        SampleCountResult(
            count=50,
            provenance=PROVENANCE_PROVIDER_VERIFIED,
            provider_name="fake-provider",
        )


def test_resolve_sample_count_still_produces_provider_verified() -> None:
    """resolve_sample_count() with a matching provider still works (non-regression)."""
    result = resolve_sample_count(
        client_claimed=200,
        provider=_FixedProvider(count=200),
        **_IDENTITY,
    )
    assert result.provenance == PROVENANCE_PROVIDER_VERIFIED
    assert result.count == 200
    assert result.provider_name == "fixed"


def test_client_claimed_construction_still_works() -> None:
    """Direct construction with CLIENT_CLAIMED provenance remains valid."""
    r = SampleCountResult(count=42, provenance=PROVENANCE_CLIENT_CLAIMED)
    assert r.count == 42
    assert r.provenance == PROVENANCE_CLIENT_CLAIMED


# ---------------------------------------------------------------------------
# Finding B2 — stub is_client_selected False branch
# ---------------------------------------------------------------------------


def test_stub_returns_false_for_known_client_in_wrong_round() -> None:
    """Corrected stub returns False (not None) for a known client in a different round."""
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1)
    result = stub.is_client_selected(client_id="cl-1", round_number=99)
    assert result is False, f"Expected False for known client in wrong round, got {result!r}"


def test_stub_returns_none_for_completely_unknown_client() -> None:
    """Stub returns None for a client that has never been registered."""
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1)
    assert stub.is_client_selected(client_id="totally-unknown", round_number=1) is None


def test_explicit_not_selected_blocks_coordinator_provider() -> None:
    """get_verified_count() returns None when is_client_selected() is False."""
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1, sample_count=100)
    provider = CoordinatorBackedSampleCountProvider(adapter=stub)

    result = provider.get_verified_count(
        client_id="cl-1",
        update_id="upd-x",
        round_number=99,
    )
    assert result is None, (
        "get_verified_count() must return None when the client is not selected for the round"
    )


def test_selected_client_in_correct_round_returns_count() -> None:
    """Non-regression: get_verified_count() works for a correctly registered client."""
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1, sample_count=150)
    provider = CoordinatorBackedSampleCountProvider(adapter=stub)

    result = provider.get_verified_count(
        client_id="cl-1",
        update_id="upd-y",
        round_number=1,
    )
    assert result == 150
