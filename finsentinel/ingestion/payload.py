
"""Payload size enforcement and SHA-256 integrity verification."""

import hashlib
import hmac

from ingestion.schemas import UpdateEnvelope

MAX_PAYLOAD_SIZE_BYTES = 500_000_000


class PayloadIntegrityError(ValueError):
    """Raised when a payload violates size or integrity requirements."""


def verify_payload(
    payload: bytes,
    envelope: UpdateEnvelope,
) -> str:
    """Validate payload size and compare its SHA-256 digest with the envelope.

    Returns the computed SHA-256 digest if verification succeeds.
    Raises PayloadIntegrityError if size or digest verification fails.
    """
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")

    actual_size = len(payload)

    if actual_size == 0:
        raise PayloadIntegrityError("Payload must not be empty")

    if actual_size > MAX_PAYLOAD_SIZE_BYTES:
        raise PayloadIntegrityError("Payload exceeds the maximum allowed size")

    if actual_size != envelope.payload_size_bytes:
        raise PayloadIntegrityError("Payload size does not match envelope")

    actual_sha256 = hashlib.sha256(payload).hexdigest()

    if not hmac.compare_digest(
        actual_sha256,
        envelope.payload_sha256.lower(),
    ):
        raise PayloadIntegrityError("Payload SHA-256 digest does not match envelope")

    return actual_sha256
