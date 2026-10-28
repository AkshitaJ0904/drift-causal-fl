
"""Development replay protection for federated-learning updates."""

import hashlib
import threading

from core.crypto import canonical_signed_data
from ingestion.schemas import UpdateEnvelope


class ReplayProtectionError(ValueError):
    """Raised when an update ID has already been used."""


_lock = threading.Lock()
_seen_updates: dict[tuple[str, str], str] = {}


def reserve_update(envelope: UpdateEnvelope) -> None:
    """Atomically reserve an update ID after authentication succeeds.

    Reuse is rejected even if the submitted content is identical.
    The stored fingerprint helps distinguish an ID reused with new content.
    """
    key = (envelope.client_id, envelope.update_id)
    fingerprint = hashlib.sha256(canonical_signed_data(envelope)).hexdigest()

    with _lock:
        previous_fingerprint = _seen_updates.get(key)

        if previous_fingerprint is not None:
            if previous_fingerprint != fingerprint:
                raise ReplayProtectionError(
                    "Update ID has already been used with different content"
                )

            raise ReplayProtectionError("Duplicate update detected")

        _seen_updates[key] = fingerprint


def clear_replay_registry() -> None:
    """Clear replay state for tests and local development only."""
    with _lock:
        _seen_updates.clear()
