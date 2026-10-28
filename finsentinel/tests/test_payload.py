
import hashlib

import pytest

from ingestion.payload import PayloadIntegrityError, verify_payload
from ingestion.schemas import UpdateEnvelope


def make_envelope(payload: bytes) -> UpdateEnvelope:
    return UpdateEnvelope.model_validate(
        {
            "update_id": "update-001",
            "client_id": "client-001",
            "model_version": "cnn-v1",
            "round_number": 1,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
            "created_at": "2026-10-21T10:00:00Z",
            "signature": "placeholder-signature",
            "signing_key_id": "key-001",
        }
    )


def test_valid_payload_is_accepted() -> None:
    payload = b"example model update"
    envelope = make_envelope(payload)

    digest = verify_payload(payload, envelope)

    assert digest == hashlib.sha256(payload).hexdigest()


def test_modified_payload_is_rejected() -> None:
    payload = b"example model update"
    envelope = make_envelope(payload)

    # Same length as the original, so the hash check is reached.
    modified_payload = b"tampered model updat"
    assert len(modified_payload) == len(payload)

    with pytest.raises(PayloadIntegrityError, match="digest"):
        verify_payload(modified_payload, envelope)


def test_wrong_declared_size_is_rejected() -> None:
    payload = b"example model update"
    envelope = make_envelope(payload)
    envelope.payload_size_bytes += 1

    with pytest.raises(PayloadIntegrityError, match="size"):
        verify_payload(payload, envelope)


def test_empty_payload_is_rejected() -> None:
    # Use a valid envelope so this test isolates the payload verifier.
    envelope = make_envelope(b"example model update")

    with pytest.raises(PayloadIntegrityError, match="empty"):
        verify_payload(b"", envelope)


def test_non_bytes_payload_is_rejected() -> None:
    envelope = make_envelope(b"example model update")

    with pytest.raises(TypeError, match="bytes"):
        verify_payload("not bytes", envelope)  # type: ignore[arg-type]
