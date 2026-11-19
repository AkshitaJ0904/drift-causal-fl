
"""Database-backed registry of trusted client public keys.

Keys are persisted to the ``trusted_keys`` table so that all worker processes
share the same trust decisions and they survive process restarts.

No in-memory cache is maintained.  Every authentication look-up issues one
database read.  For security-critical authentication, the cost is acceptable
and eliminates the risk of stale-cache authorisation of a revoked key.

Fail-closed design: any database error during ``get_trusted_key`` raises
``RegistryUnavailableError``, blocking the request rather than passing a
degraded store result that could be confused with "key not found".
"""

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_public_key,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from audit.outbox import enqueue
from core.supabase.session import SessionLocal
from db.models.trusted_key import TrustedKeyRecord

logger = logging.getLogger(__name__)

_SAFE_ENVIRONMENTS: frozenset[str] = frozenset({"test", "development", "dev", "local"})


class RegistryUnavailableError(RuntimeError):
    """Raised when the registry DB is unreachable during a security-critical read."""


@dataclass(frozen=True)
class TrustedKey:
    """A public key authorized to sign updates for one client."""

    key_id: str
    client_id: str
    public_key: Ed25519PublicKey
    max_sample_count: int | None


def _serialize_public_key(public_key: Ed25519PublicKey) -> str:
    return public_key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def _deserialize_public_key(pem: str) -> Ed25519PublicKey:
    key = load_pem_public_key(pem.encode("ascii"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Stored key is not an Ed25519 public key.")
    return key


def register_trusted_key(
    key_id: str,
    client_id: str,
    public_key: Ed25519PublicKey,
    *,
    max_sample_count: int | None = None,
) -> None:
    """Persist a trusted key to the database.

    If *key_id* already exists and is active, the record is updated.
    If *key_id* exists but was revoked, ``ValueError`` is raised.

    Call this only from trusted provisioning code, never from an
    unauthenticated client request.
    """
    if not key_id or not client_id:
        raise ValueError("key_id and client_id must not be empty")
    if max_sample_count is not None and (
        isinstance(max_sample_count, bool)
        or not isinstance(max_sample_count, int)
        or max_sample_count <= 0
    ):
        raise ValueError("max_sample_count must be a positive integer or None.")

    pem = _serialize_public_key(public_key)

    try:
        with SessionLocal() as db:
            existing = db.scalar(
                select(TrustedKeyRecord).where(TrustedKeyRecord.key_id == key_id)
            )
            if existing is not None:
                if not existing.is_active:
                    raise ValueError(
                        f"Key {key_id!r} has been revoked and cannot be re-registered."
                    )
                existing.client_id = client_id
                existing.public_key_pem = pem
                existing.max_sample_count = max_sample_count
                enqueue(
                    db,
                    event_id=None,
                    event_type="key.registered",
                    severity="info",
                    description=f"Trusted key {key_id!r} updated for client {client_id!r}",
                    client_id=client_id,
                    update_id=None,
                )
                db.commit()
            else:
                record = TrustedKeyRecord(
                    key_id=key_id,
                    client_id=client_id,
                    public_key_pem=pem,
                    max_sample_count=max_sample_count,
                    is_active=True,
                )
                db.add(record)
                enqueue(
                    db,
                    event_id=None,
                    event_type="key.registered",
                    severity="info",
                    description=f"Trusted key {key_id!r} registered for client {client_id!r}",
                    client_id=client_id,
                    update_id=None,
                )
                try:
                    db.commit()
                except IntegrityError as exc:
                    db.rollback()
                    raise ValueError(
                        f"Key {key_id!r} was concurrently registered."
                    ) from exc
    except ValueError:
        raise
    except SQLAlchemyError as exc:
        logger.exception("DB error registering trusted key %r", key_id)
        raise RegistryUnavailableError(
            f"Registry unavailable while registering key {key_id!r}"
        ) from exc


def get_trusted_key(key_id: str) -> TrustedKey | None:
    """Look up an active trusted public key by its identifier.

    Returns ``None`` if the key is not found or has been revoked.
    Raises ``RegistryUnavailableError`` on any database failure so that
    callers can distinguish "not found" from "DB down" (fail-closed).
    """
    try:
        with SessionLocal() as db:
            record = db.scalar(
                select(TrustedKeyRecord).where(
                    TrustedKeyRecord.key_id == key_id,
                    TrustedKeyRecord.is_active.is_(True),
                )
            )
    except SQLAlchemyError as exc:
        logger.exception("DB error looking up trusted key %r", key_id)
        raise RegistryUnavailableError(
            f"Registry unavailable while looking up key {key_id!r}"
        ) from exc

    if record is None:
        return None

    try:
        public_key = _deserialize_public_key(record.public_key_pem)
    except Exception as exc:
        logger.exception(
            "Failed to deserialize stored PEM for key %r — record may be corrupted",
            key_id,
        )
        raise RegistryUnavailableError(
            f"Stored public key for {key_id!r} is corrupted or invalid"
        ) from exc

    return TrustedKey(
        key_id=record.key_id,
        client_id=record.client_id,
        public_key=public_key,
        max_sample_count=record.max_sample_count,
    )


def revoke_trusted_key(key_id: str) -> bool:
    """Mark a key as revoked so it can no longer authenticate updates.

    Returns ``True`` if the key was found and revoked, ``False`` if it was
    not found or was already revoked.  Raises ``RegistryUnavailableError``
    on any database failure.
    """
    try:
        with SessionLocal() as db:
            record = db.scalar(
                select(TrustedKeyRecord).where(TrustedKeyRecord.key_id == key_id)
            )
            if record is None or not record.is_active:
                return False
            record.is_active = False
            record.revoked_at = datetime.now(tz=UTC)
            enqueue(
                db,
                event_id=None,
                event_type="key.revoked",
                severity="warning",
                description=f"Trusted key {key_id!r} revoked for client {record.client_id!r}",
                client_id=record.client_id,
                update_id=None,
            )
            db.commit()
            return True
    except SQLAlchemyError as exc:
        logger.exception("DB error revoking trusted key %r", key_id)
        raise RegistryUnavailableError(
            f"Registry unavailable while revoking key {key_id!r}"
        ) from exc


def clear_trusted_keys() -> None:
    """Delete all trusted key records.  For tests and local development only.

    Raises ``RuntimeError`` if the ``ENVIRONMENT`` variable is not set to a
    recognised safe value to prevent accidental production truncation.
    """
    environment = os.environ.get("ENVIRONMENT", "").lower()
    if environment not in _SAFE_ENVIRONMENTS:
        raise RuntimeError(
            f"clear_trusted_keys() refuses to run in ENVIRONMENT={environment!r}. "
            "Only 'test', 'development', 'dev', or 'local' environments are permitted."
        )
    try:
        with SessionLocal() as db:
            db.execute(delete(TrustedKeyRecord))
            db.commit()
    except SQLAlchemyError as exc:
        logger.exception("DB error clearing trusted keys")
        raise RegistryUnavailableError("Registry unavailable while clearing keys") from exc
