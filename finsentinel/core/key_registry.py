
"""In-memory registry of trusted client public keys.

For the initial development version only. Production key records must be
loaded from a controlled, persistent trust store.
"""

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


@dataclass(frozen=True)
class TrustedKey:
    """A public key authorized to sign updates for one client."""

    key_id: str
    client_id: str
    public_key: Ed25519PublicKey


_TRUSTED_KEYS: dict[str, TrustedKey] = {}


def register_trusted_key(
    key_id: str,
    client_id: str,
    public_key: Ed25519PublicKey,
) -> None:
    """Register a trusted key.

    Call this only from trusted provisioning code, never directly from
    an unauthenticated client request.
    """
    if not key_id or not client_id:
        raise ValueError("key_id and client_id must not be empty")

    _TRUSTED_KEYS[key_id] = TrustedKey(
        key_id=key_id,
        client_id=client_id,
        public_key=public_key,
    )


def get_trusted_key(key_id: str) -> TrustedKey | None:
    """Look up a trusted public key by its identifier."""
    return _TRUSTED_KEYS.get(key_id)


def clear_trusted_keys() -> None:
    """Clear registry entries. Intended for tests and development."""
    _TRUSTED_KEYS.clear()
