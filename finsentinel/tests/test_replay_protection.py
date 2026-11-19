
"""Tests for update replay protection and reservation ownership."""

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


def make_envelope(
    update_id: str = "update-001",
    payload: bytes = b"example model update",
) -> UpdateEnvelope:
    return UpdateEnvelope.model_validate(
        {
            "update_id": update_id,
            "client_id": "client-001",
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
    clear_replay_registry()


def test_first_use_of_update_id_is_accepted_and_returns_token() -> None:
    token = reserve_update(make_envelope())
    assert isinstance(token, str)
    assert len(token) >= 16


def test_duplicate_update_is_rejected() -> None:
    envelope = make_envelope()
    reserve_update(envelope)

    with pytest.raises(ReplayProtectionError, match="Duplicate update"):
        reserve_update(envelope)


def test_reused_id_with_different_content_is_rejected() -> None:
    reserve_update(make_envelope())

    changed_envelope = make_envelope(
        payload=b"different model update"
    )

    with pytest.raises(ReplayProtectionError, match="different content"):
        reserve_update(changed_envelope)


def test_different_update_ids_are_accepted() -> None:
    token1 = reserve_update(make_envelope("update-001"))
    token2 = reserve_update(make_envelope("update-002"))
    assert token1 != token2


def test_release_reservation_with_owner_token_allows_retry() -> None:
    envelope = make_envelope("update-001")
    token = reserve_update(envelope)

    # Cannot re-reserve while active
    with pytest.raises(ReplayProtectionError):
        reserve_update(envelope)

    # Release reservation with valid token
    released = release_update_reservation(
        client_id=envelope.client_id,
        update_id=envelope.update_id,
        token=token,
    )
    assert released is True

    # Now re-reservation succeeds
    new_token = reserve_update(envelope)
    assert isinstance(new_token, str)


def test_release_with_wrong_token_is_rejected_and_preserves_reservation() -> None:
    envelope = make_envelope("update-001")
    reserve_update(envelope)

    # Attempt to release using unauthorized token
    released = release_update_reservation(
        client_id=envelope.client_id,
        update_id=envelope.update_id,
        token="invalid-unauthorized-token",
    )
    assert released is False

    # Reservation remains active and blocks duplicate
    with pytest.raises(ReplayProtectionError):
        reserve_update(envelope)


def test_cannot_release_after_finalization() -> None:
    envelope = make_envelope("update-001")
    token = reserve_update(envelope)

    # Finalize reservation upon successful DB registration
    finalized = finalize_update_reservation(
        client_id=envelope.client_id,
        update_id=envelope.update_id,
        token=token,
    )
    assert finalized is True
    assert (
        is_reservation_finalized(client_id=envelope.client_id, update_id=envelope.update_id)
        is True
    )

    # Even the original token CANNOT release a finalized reservation
    released = release_update_reservation(
        client_id=envelope.client_id,
        update_id=envelope.update_id,
        token=token,
    )
    assert released is False

    # Still blocks duplicates
    with pytest.raises(ReplayProtectionError):
        reserve_update(envelope)


def test_concurrent_duplicate_reservations() -> None:
    envelope = make_envelope("update-concurrent")
    num_threads = 10

    def try_reserve():
        try:
            return reserve_update(envelope)
        except ReplayProtectionError:
            return None

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(try_reserve) for _ in range(num_threads)]
        results = [f.result() for f in futures]

    # Exactly one thread must have succeeded in obtaining a token
    successful_tokens = [r for r in results if r is not None]
    assert len(successful_tokens) == 1
