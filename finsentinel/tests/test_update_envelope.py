
import pytest
from pydantic import ValidationError

from ingestion.schemas import UpdateEnvelope


def valid_envelope() -> dict:
    return {
        "update_id": "update-001",
        "client_id": "client-001",
        "model_version": "cnn-v1",
        "round_number": 1,
        "sample_count": 1,
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


@pytest.mark.parametrize("value", [0, -1, True])
def test_invalid_sample_count_is_rejected(value: int | bool) -> None:
    data = valid_envelope()
    data["sample_count"] = value

    with pytest.raises(ValidationError):
        UpdateEnvelope.model_validate(data)


# ── round_number strict-integer tests ────────────────────────────────────────

def test_valid_round_number_is_accepted() -> None:
    envelope = UpdateEnvelope.model_validate(valid_envelope())
    assert envelope.round_number == 1


@pytest.mark.parametrize("value", [True, False])
def test_boolean_round_number_is_rejected(value: bool) -> None:
    data = valid_envelope()
    data["round_number"] = value
    with pytest.raises(ValidationError):
        UpdateEnvelope.model_validate(data)


@pytest.mark.parametrize("value", ["1", "2", "1.0"])
def test_string_round_number_is_rejected(value: str) -> None:
    data = valid_envelope()
    data["round_number"] = value
    with pytest.raises(ValidationError):
        UpdateEnvelope.model_validate(data)


@pytest.mark.parametrize("value", [0, -1, -100])
def test_non_positive_round_number_is_rejected(value: int) -> None:
    data = valid_envelope()
    data["round_number"] = value
    with pytest.raises(ValidationError):
        UpdateEnvelope.model_validate(data)


# ── payload_size_bytes strict-integer tests ───────────────────────────────────

def test_valid_payload_size_is_accepted() -> None:
    data = valid_envelope()
    data["payload_size_bytes"] = 1024
    envelope = UpdateEnvelope.model_validate(data)
    assert envelope.payload_size_bytes == 1024


@pytest.mark.parametrize("value", [True, False])
def test_boolean_payload_size_is_rejected(value: bool) -> None:
    data = valid_envelope()
    data["payload_size_bytes"] = value
    with pytest.raises(ValidationError):
        UpdateEnvelope.model_validate(data)


@pytest.mark.parametrize("value", ["1024", "500", "1"])
def test_string_payload_size_is_rejected(value: str) -> None:
    data = valid_envelope()
    data["payload_size_bytes"] = value
    with pytest.raises(ValidationError):
        UpdateEnvelope.model_validate(data)


@pytest.mark.parametrize("value", [-1, -1024])
def test_negative_payload_size_is_rejected(value: int) -> None:
    data = valid_envelope()
    data["payload_size_bytes"] = value
    with pytest.raises(ValidationError):
        UpdateEnvelope.model_validate(data)
