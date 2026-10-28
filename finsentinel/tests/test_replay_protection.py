
"""Tests for update replay protection."""

import hashlib

import pytest

from core.replay_protection import (
    ReplayProtectionError,
    clear_replay_registry,
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


def test_first_use_of_update_id_is_accepted() -> None:
    reserve_update(make_envelope())


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
    reserve_update(make_envelope("update-001"))
    reserve_update(make_envelope("update-002"))
