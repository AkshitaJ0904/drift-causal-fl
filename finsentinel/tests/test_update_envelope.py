
import pytest
from pydantic import ValidationError

from ingestion.schemas import UpdateEnvelope


def valid_envelope() -> dict:
    return {
        "update_id": "update-001",
        "client_id": "client-001",
        "model_version": "cnn-v1",
        "round_number": 1,
        "payload_sha256": "a" * 64,
        "payload_size_bytes": 1024,
        "created_at": "2026-10-21T10:00:00Z",
        "signature": "placeholder-signature",
        "signing_key_id": "key-001",
    }


def test_valid_envelope_is_accepted() -> None:
    envelope = UpdateEnvelope.model_validate(valid_envelope())

    assert envelope.update_id == "update-001"
    assert envelope.round_number == 1


def test_invalid_hash_is_rejected() -> None:
    data = valid_envelope()
    data["payload_sha256"] = "not-a-hash"

    with pytest.raises(ValidationError):
        UpdateEnvelope.model_validate(data)


def test_naive_timestamp_is_rejected() -> None:
    data = valid_envelope()
    data["created_at"] = "2026-10-21T10:00:00"

    with pytest.raises(ValidationError):
        UpdateEnvelope.model_validate(data)


def test_unexpected_field_is_rejected() -> None:
    data = valid_envelope()
    data["admin_override"] = True

    with pytest.raises(ValidationError):
        UpdateEnvelope.model_validate(data)


def test_zero_payload_size_is_rejected() -> None:
    data = valid_envelope()
    data["payload_size_bytes"] = 0

    with pytest.raises(ValidationError):
        UpdateEnvelope.model_validate(data)
