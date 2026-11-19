"""Tests for the FL coordinator adapter interface.

Coverage:
 - StubCoordinatorAdapter.name == "stub-coordinator"
 - StubCoordinatorAdapter satisfies CoordinatorAdapter Protocol
 - CoordinatorBackedSampleCountProvider satisfies SampleCountProvider Protocol
 - Registered client, general entry → correct sample count returned
 - Registered client, update_id-specific entry → matches by update_id
 - Registered client, update_id-specific entry → no match for different update_id
 - Registered client, no sample_count → None returned
 - Unregistered client → None returned
 - is_client_selected: registered → True; unknown → None
 - register_participation validation: invalid sample_count raises
 - CoordinatorBackedSampleCountProvider.name prefixes adapter name
 - Integration: CoordinatorBackedSampleCountProvider → resolve_sample_count match
 - Integration: resolve_sample_count mismatch raises SampleCountMismatchError
 - Integration: provider returns None → CLIENT_CLAIMED
 - Integration: require_verified + provider None → SampleCountVerificationError
 - clear() removes all entries
"""

from __future__ import annotations

from typing import TypedDict

import pytest

from coordination.coordinator_adapter import (
    CoordinatorAdapter,
    CoordinatorBackedSampleCountProvider,
)
from coordination.stub_coordinator import StubCoordinatorAdapter
from ingestion.sample_count_provider import (
    PROVENANCE_CLIENT_CLAIMED,
    PROVENANCE_PROVIDER_VERIFIED,
    SampleCountMismatchError,
    SampleCountProvider,
    SampleCountVerificationError,
    resolve_sample_count,
)


class _IdentityKwargs(TypedDict):
    client_id: str
    update_id: str
    round_number: int

_IDENTITY: _IdentityKwargs = {"client_id": "cl-1", "update_id": "upd-1", "round_number": 1}


# ---------------------------------------------------------------------------
# StubCoordinatorAdapter basics
# ---------------------------------------------------------------------------


def test_stub_name() -> None:
    assert StubCoordinatorAdapter().name == "stub-coordinator"


def test_stub_satisfies_coordinator_protocol() -> None:
    assert isinstance(StubCoordinatorAdapter(), CoordinatorAdapter)


def test_backed_provider_satisfies_sample_count_protocol() -> None:
    provider = CoordinatorBackedSampleCountProvider(StubCoordinatorAdapter())
    assert isinstance(provider, SampleCountProvider)


def test_backed_provider_name_prefixes_adapter() -> None:
    stub = StubCoordinatorAdapter()
    p = CoordinatorBackedSampleCountProvider(stub)
    assert p.name == "coordinator:stub-coordinator"


# ---------------------------------------------------------------------------
# get_expected_sample_count — round-level (general) entries
# ---------------------------------------------------------------------------


def test_registered_client_returns_sample_count() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1, sample_count=200)
    assert stub.get_expected_sample_count(client_id="cl-1", update_id="any", round_number=1) == 200


def test_unregistered_client_returns_none() -> None:
    stub = StubCoordinatorAdapter()
    result = stub.get_expected_sample_count(client_id="unknown", update_id="u", round_number=1)
    assert result is None


def test_registered_client_wrong_round_returns_none() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1, sample_count=100)
    assert stub.get_expected_sample_count(client_id="cl-1", update_id="u", round_number=2) is None


def test_registered_no_sample_count_returns_none() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1, sample_count=None)
    assert stub.get_expected_sample_count(client_id="cl-1", update_id="u", round_number=1) is None


# ---------------------------------------------------------------------------
# get_expected_sample_count — update_id-specific entries
# ---------------------------------------------------------------------------


def test_specific_update_id_matches() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(
        client_id="cl-1", round_number=1, sample_count=150, update_id="upd-abc"
    )
    result = stub.get_expected_sample_count(
        client_id="cl-1", update_id="upd-abc", round_number=1
    )
    assert result == 150


def test_specific_update_id_no_match_returns_none() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(
        client_id="cl-1", round_number=1, sample_count=150, update_id="upd-abc"
    )
    result = stub.get_expected_sample_count(
        client_id="cl-1", update_id="upd-xyz", round_number=1
    )
    assert result is None


def test_specific_entry_preferred_over_general() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1, sample_count=100)
    stub.register_participation(
        client_id="cl-1", round_number=1, sample_count=200, update_id="upd-specific"
    )
    specific = stub.get_expected_sample_count(
        client_id="cl-1", update_id="upd-specific", round_number=1
    )
    general = stub.get_expected_sample_count(
        client_id="cl-1", update_id="other-upd", round_number=1
    )
    assert specific == 200
    assert general == 100


# ---------------------------------------------------------------------------
# is_client_selected
# ---------------------------------------------------------------------------


def test_is_client_selected_registered_true() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1)
    assert stub.is_client_selected(client_id="cl-1", round_number=1) is True


def test_is_client_selected_unknown_none() -> None:
    stub = StubCoordinatorAdapter()
    assert stub.is_client_selected(client_id="unknown", round_number=1) is None


def test_is_client_selected_wrong_round_false() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1)
    assert stub.is_client_selected(client_id="cl-1", round_number=5) is False


# ---------------------------------------------------------------------------
# register_participation validation
# ---------------------------------------------------------------------------


def test_register_zero_sample_count_raises() -> None:
    stub = StubCoordinatorAdapter()
    with pytest.raises(ValueError, match="positive integer"):
        stub.register_participation(client_id="c", round_number=1, sample_count=0)


def test_register_negative_sample_count_raises() -> None:
    stub = StubCoordinatorAdapter()
    with pytest.raises(ValueError, match="positive integer"):
        stub.register_participation(client_id="c", round_number=1, sample_count=-5)


def test_register_bool_sample_count_raises() -> None:
    stub = StubCoordinatorAdapter()
    with pytest.raises(ValueError, match="positive integer"):
        stub.register_participation(client_id="c", round_number=1, sample_count=True)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------


def test_clear_removes_entries() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1, sample_count=100)
    stub.clear()
    assert stub.get_expected_sample_count(client_id="cl-1", update_id="u", round_number=1) is None
    assert stub.is_client_selected(client_id="cl-1", round_number=1) is None


# ---------------------------------------------------------------------------
# Integration: CoordinatorBackedSampleCountProvider → resolve_sample_count
# ---------------------------------------------------------------------------


def test_integration_match_returns_provider_verified() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1, sample_count=300)
    provider = CoordinatorBackedSampleCountProvider(stub)

    result = resolve_sample_count(
        client_claimed=300,
        provider=provider,
        **_IDENTITY,
    )
    assert result.provenance == PROVENANCE_PROVIDER_VERIFIED
    assert result.count == 300
    assert result.provider_name == "coordinator:stub-coordinator"


def test_integration_mismatch_raises() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1, sample_count=400)
    provider = CoordinatorBackedSampleCountProvider(stub)

    with pytest.raises(SampleCountMismatchError, match="400"):
        resolve_sample_count(
            client_claimed=300,
            provider=provider,
            **_IDENTITY,
        )


def test_integration_unregistered_falls_back_to_client_claimed() -> None:
    stub = StubCoordinatorAdapter()
    provider = CoordinatorBackedSampleCountProvider(stub)

    result = resolve_sample_count(
        client_claimed=50,
        provider=provider,
        **_IDENTITY,
    )
    assert result.provenance == PROVENANCE_CLIENT_CLAIMED
    assert result.count == 50


def test_integration_require_verified_unregistered_raises() -> None:
    stub = StubCoordinatorAdapter()
    provider = CoordinatorBackedSampleCountProvider(stub)

    with pytest.raises(SampleCountVerificationError, match="could not verify"):
        resolve_sample_count(
            client_claimed=50,
            provider=provider,
            require_verified=True,
            **_IDENTITY,
        )


def test_integration_no_sample_count_registered_falls_back() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1, sample_count=None)
    provider = CoordinatorBackedSampleCountProvider(stub)

    result = resolve_sample_count(
        client_claimed=75,
        provider=provider,
        **_IDENTITY,
    )
    assert result.provenance == PROVENANCE_CLIENT_CLAIMED


def test_integration_require_verified_no_sample_count_raises() -> None:
    stub = StubCoordinatorAdapter()
    stub.register_participation(client_id="cl-1", round_number=1, sample_count=None)
    provider = CoordinatorBackedSampleCountProvider(stub)

    with pytest.raises(SampleCountVerificationError):
        resolve_sample_count(
            client_claimed=75,
            provider=provider,
            require_verified=True,
            **_IDENTITY,
        )
