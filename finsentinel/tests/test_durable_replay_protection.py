
"""Tests for durable (database-backed) replay protection.

Verifies that replay records survive in-memory clears, that concurrent
threads produce exactly one success, and that finalization persists through
memory clears.  Uses the ``include_database=False`` variant of
``clear_replay_registry`` to clear only the in-memory dict while leaving
DB rows intact, exercising the cross-restart durability path.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.replay_protection import (
    ReplayProtectionError,
    clear_replay_registry,
    finalize_update_reservation,
    is_reservation_finalized,
    release_update_reservation,
    reserve_update,
)
from ingestion.schemas import UpdateEnvelope


def _make_envelope(
    update_id: str = "update-durable-001",
    client_id: str = "client-durable-001",
    payload: bytes = b"durable model update",
) -> UpdateEnvelope:
    return UpdateEnvelope.model_validate(
        {
            "update_id": update_id,
            "client_id": client_id,
            "model_version": "cnn-v1",
            "round_number": 1,
            "sample_count": 1,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
            "created_at": "2026-10-21T10:00:00Z",
            "signature": "test-signature",
            "signing_key_id": "key-001",
        }
    )


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    clear_replay_registry(include_database=True)


# ---------------------------------------------------------------------------
# Cross-restart durability: reservation survives in-memory clear
# ---------------------------------------------------------------------------

def test_reservation_survives_in_memory_clear() -> None:
    """After clearing only in-memory state, the DB blocks re-reservation."""
    envelope = _make_envelope("durable-persist-001")
    reserve_update(envelope)

    # Simulate a process restart: clear in-memory only, DB row remains.
    clear_replay_registry(include_database=False)

    with pytest.raises(ReplayProtectionError, match="Duplicate update"):
        reserve_update(envelope)


def test_different_fingerprint_after_memory_clear_raises_replay_error() -> None:
    """After in-memory clear, re-submitting with different content is blocked by DB."""
    envelope = _make_envelope("durable-fingerprint-001")
    reserve_update(envelope)

    clear_replay_registry(include_database=False)

    different_envelope = _make_envelope(
        update_id="durable-fingerprint-001",
        payload=b"different content",
    )
    with pytest.raises(ReplayProtectionError, match="different content"):
        reserve_update(different_envelope)


def test_full_clear_allows_re_reservation() -> None:
    """After clearing both in-memory and DB, the same update can be reserved again."""
    envelope = _make_envelope("durable-full-clear-001")
    reserve_update(envelope)

    clear_replay_registry(include_database=True)

    # Both stores are empty; re-reservation should succeed.
    new_token = reserve_update(envelope)
    assert isinstance(new_token, str)
    assert len(new_token) >= 16


# ---------------------------------------------------------------------------
# Finalization persistence
# ---------------------------------------------------------------------------

def test_finalized_reservation_survives_in_memory_clear() -> None:
    """is_reservation_finalized falls back to DB when in-memory is cleared."""
    envelope = _make_envelope("durable-finalized-001")
    token = reserve_update(envelope)
    finalized = finalize_update_reservation(
        client_id=envelope.client_id,
        update_id=envelope.update_id,
        token=token,
    )
    assert finalized is True

    clear_replay_registry(include_database=False)

    # In-memory is gone; DB still has the finalized record.
    assert is_reservation_finalized(
        client_id=envelope.client_id,
        update_id=envelope.update_id,
    ) is True


def test_finalized_reservation_blocks_re_reservation_after_memory_clear() -> None:
    """A finalized DB record prevents re-reservation after a simulated restart."""
    envelope = _make_envelope("durable-finalized-block-001")
    token = reserve_update(envelope)
    finalize_update_reservation(
        client_id=envelope.client_id,
        update_id=envelope.update_id,
        token=token,
    )

    clear_replay_registry(include_database=False)

    with pytest.raises(ReplayProtectionError):
        reserve_update(envelope)


# ---------------------------------------------------------------------------
# Release durability
# ---------------------------------------------------------------------------

def test_release_removes_db_record_and_allows_retry() -> None:
    """After release, DB record is deleted and re-reservation succeeds."""
    envelope = _make_envelope("durable-release-001")
    token = reserve_update(envelope)

    released = release_update_reservation(
        client_id=envelope.client_id,
        update_id=envelope.update_id,
        token=token,
    )
    assert released is True

    # DB row was deleted; retry should succeed even after in-memory is cleared.
    clear_replay_registry(include_database=False)
    new_token = reserve_update(envelope)
    assert isinstance(new_token, str)


# ---------------------------------------------------------------------------
# Concurrent reservations: exactly one succeeds
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Production guard: clear_replay_registry must refuse in non-test environments
# ---------------------------------------------------------------------------

def test_clear_replay_registry_raises_outside_safe_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """clear_replay_registry() must raise RuntimeError outside safe environments."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="refuses to run"):
        clear_replay_registry(include_database=False)


def test_clear_replay_registry_raises_in_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """clear_replay_registry() must refuse in staging, not just production."""
    monkeypatch.setenv("ENVIRONMENT", "staging")
    with pytest.raises(RuntimeError, match="refuses to run"):
        clear_replay_registry(include_database=True)


def test_clear_replay_registry_raises_when_environment_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """clear_replay_registry() must refuse when ENVIRONMENT is not set."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(RuntimeError, match="refuses to run"):
        clear_replay_registry(include_database=False)


# ---------------------------------------------------------------------------
# Concurrent reservations: exactly one succeeds
# ---------------------------------------------------------------------------

def test_concurrent_reservations_exactly_one_succeeds() -> None:
    """Under concurrent load exactly one reservation wins the DB unique constraint."""
    envelope = _make_envelope("durable-concurrent-001")
    num_threads = 10

    def try_reserve() -> str | None:
        try:
            return reserve_update(envelope)
        except ReplayProtectionError:
            return None

    with ThreadPoolExecutor(max_workers=num_threads) as pool:
        futures = [pool.submit(try_reserve) for _ in range(num_threads)]
        results = [f.result() for f in futures]

    successful_tokens = [r for r in results if r is not None]
    assert len(successful_tokens) == 1
