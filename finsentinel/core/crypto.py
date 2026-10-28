
"""Ed25519 signing and verification utilities."""

import base64
import binascii
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ingestion.schemas import UpdateEnvelope


def canonical_signed_data(envelope: UpdateEnvelope) -> bytes:
    """Serialize signed metadata deterministically, excluding the signature."""
    metadata = envelope.model_dump(mode="json", exclude={"signature"})

    return json.dumps(
        metadata,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign_envelope(
    envelope: UpdateEnvelope,
    private_key: Ed25519PrivateKey,
) -> str:
    """Sign envelope metadata and return the signature as Base64."""
    signature = private_key.sign(canonical_signed_data(envelope))
    return base64.b64encode(signature).decode("ascii")


def verify_envelope_signature(
    envelope: UpdateEnvelope,
    public_key: Ed25519PublicKey,
) -> bool:
    """Verify the Base64-encoded signature over the envelope metadata."""
    try:
        signature = base64.b64decode(envelope.signature, validate=True)
        public_key.verify(signature, canonical_signed_data(envelope))
    except (binascii.Error, ValueError, InvalidSignature):
        return False

    return True
