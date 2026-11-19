
"""Database-backed replay protection for federated-learning updates.

Each update reservation is written to the ``replay_records`` database table
(authoritative store) in addition to the in-memory registry.  This prevents
duplicate submissions across process restarts and multiple worker processes.

The in-memory lock (``_lock``) guards intra-process thread safety and provides
a fast-path check that avoids a database round-trip for obvious same-process
duplicates.

Fail-closed design: any database error during ``reserve_update`` raises
``ReplayProtectionError``, blocking the update rather than allowing it through
on a degraded store.
"""

import hashlib
import hmac
import logging
import os
import secrets
import threading
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError

from core.crypto import canonical_signed_data
from core.supabase.session import SessionLocal
from db.models.replay_record import ReplayRecord
from ingestion.schemas import UpdateEnvelope

logger = logging.getLogger(__name__)


class ReplayProtectionError(ValueError):
    """Raised when an update ID has already been used."""


@dataclass
class _ReservationEntry:
    fingerprint: str
    token: str
    finalized: bool = False


_lock = threading.Lock()
_seen_updates: dict[tuple[str, str], _ReservationEntry] = {}


def reserve_update(envelope: UpdateEnvelope) -> str:
    """Atomically reserve an update ID after authentication succeeds.

    Returns a unique reservation token proving reservation ownership.
    This token is required to release the reservation if downstream
    processing fails.  Reuse of the update ID is rejected under all
    circumstances, including after a process restart.
    """
    key = (envelope.client_id, envelope.update_id)
    fingerprint = hashlib.sha256(canonical_signed_data(envelope)).hexdigest()

    # Fast path: in-memory check (no DB round-trip for same-process duplicates)
    with _lock:
        entry = _seen_updates.get(key)
        if entry is not None:
            if entry.fingerprint != fingerprint:
                raise ReplayProtectionError(
                    "Update ID has already been used with different content"
                )
            raise ReplayProtectionError("Duplicate update detected")

    # Authoritative durable check: insert into DB.
    # The unique constraint on (client_id, update_id) is the replay gate.
    row = ReplayRecord(
        client_id=envelope.client_id,
        update_id=envelope.update_id,
        payload_fingerprint=fingerprint,
        finalized=False,
    )
    try:
        with SessionLocal() as db:
            with db.begin():
                db.add(row)
    except IntegrityError:
        # Duplicate from another worker or a previous run.
        try:
            with SessionLocal() as db:
                existing = db.scalar(
                    select(ReplayRecord).where(
                        ReplayRecord.client_id == envelope.client_id,
                        ReplayRecord.update_id == envelope.update_id,
                    )
                )
        except Exception:
            existing = None
        if existing is not None and existing.payload_fingerprint != fingerprint:
            raise ReplayProtectionError(
                "Update ID has already been used with different content"
            ) from None
        raise ReplayProtectionError("Duplicate update detected") from None
    except Exception as exc:
        # Any DB error is fail-closed: replay protection cannot be bypassed.
        raise ReplayProtectionError(
            f"Replay protection is unavailable: {type(exc).__name__}"
        ) from exc

    token = secrets.token_hex(16)
    with _lock:
        _seen_updates[key] = _ReservationEntry(
            fingerprint=fingerprint, token=token, finalized=False
        )
    return token


def release_update_reservation(
    *,
    client_id: str,
    update_id: str,
    token: str,
) -> bool:
    """Release a reserved update ID if subsequent processing fails.

    A reservation can ONLY be released by the caller presenting the exact token
    issued by reserve_update. Once a reservation has been finalized (e.g. after
    successful database registration), it can NEVER be released.

    Returns True if the reservation was successfully released, False otherwise.
    """
    if not token or not token.strip():
        return False

    key = (client_id, update_id)
    with _lock:
        entry = _seen_updates.get(key)
        if entry is None:
            return False

        if entry.finalized:
            return False

        if not hmac.compare_digest(entry.token, token):
            return False

        try:
            with SessionLocal() as db:
                with db.begin():
                    result = db.execute(
                        delete(ReplayRecord).where(
                            ReplayRecord.client_id == client_id,
                            ReplayRecord.update_id == update_id,
                            ReplayRecord.finalized == False,  # noqa: E712
                        )
                    )
                    if result.rowcount == 0:  # type: ignore[attr-defined]
                        # No unfinalized row was deleted.  Determine whether the row
                        # is finalized (ambiguous commit) or absent (stale entry).
                        row = db.scalar(
                            select(ReplayRecord).where(
                                ReplayRecord.client_id == client_id,
                                ReplayRecord.update_id == update_id,
                            )
                        )
                        if row is not None and row.finalized:
                            # The DB row is finalized: the approval+finalization
                            # transaction committed even though the caller did not
                            # receive acknowledgment.  Sync the in-memory flag and
                            # refuse to release — the reservation is durable.
                            entry.finalized = True
                            return False
                        # Row absent (stale in-memory entry): fall through to clear.
        except Exception:
            # DB error: refuse to clear in-memory entry (fail-closed).
            return False

        del _seen_updates[key]
        return True


def finalize_update_reservation(
    *,
    client_id: str,
    update_id: str,
    token: str,
) -> bool:
    """Mark a reservation as finalized upon successful database registration.

    Once finalized, the reservation cannot be released or rolled back by any
    caller.  Returns True if finalized, False if token mismatch or key not found.
    """
    if not token or not token.strip():
        return False

    key = (client_id, update_id)
    with _lock:
        entry = _seen_updates.get(key)
        if entry is None:
            return False

        if not hmac.compare_digest(entry.token, token):
            return False

        try:
            with SessionLocal() as db:
                with db.begin():
                    db.execute(
                        sa_update(ReplayRecord)
                        .where(
                            ReplayRecord.client_id == client_id,
                            ReplayRecord.update_id == update_id,
                        )
                        .values(finalized=True)
                    )
        except Exception:
            return False

        entry.finalized = True
        return True


def mark_reservation_finalized_in_memory(
    *,
    client_id: str,
    update_id: str,
    token: str,
) -> bool:
    """Mark a reservation as finalized in the in-memory cache only.

    Called after register_and_finalize_validated_update() commits the combined
    DB transaction.  Updates only the in-memory entry so that
    is_reservation_finalized() fast-path returns True without a DB round-trip.

    Returns True if the entry was updated, False if the token does not match or
    the key is not present (e.g. after a process restart — the DB row is already
    finalized and is_reservation_finalized() will confirm via DB fallback).
    """
    if not token or not token.strip():
        return False

    key = (client_id, update_id)
    with _lock:
        entry = _seen_updates.get(key)
        if entry is None:
            return False
        if not hmac.compare_digest(entry.token, token):
            return False
        entry.finalized = True
        return True


def is_reservation_finalized(
    *,
    client_id: str,
    update_id: str,
) -> bool:
    """Check if an update reservation is finalized.

    Checks in-memory first (fast path), then falls back to the database for
    cross-restart queries.
    """
    key = (client_id, update_id)
    with _lock:
        entry = _seen_updates.get(key)
        if entry is not None:
            return entry.finalized

    # Fall back to DB for cross-restart queries.
    try:
        with SessionLocal() as db:
            row = db.scalar(
                select(ReplayRecord).where(
                    ReplayRecord.client_id == client_id,
                    ReplayRecord.update_id == update_id,
                )
            )
            return row is not None and row.finalized
    except Exception:
        return False


_SAFE_ENVIRONMENTS: frozenset[str] = frozenset({"test", "development", "dev", "local"})


def clear_replay_registry(*, include_database: bool = True) -> None:
    """Clear replay state for tests and local development only.

    Raises ``RuntimeError`` if the ``ENVIRONMENT`` variable is not set to a
    recognised safe value ("test", "development", "dev", "local") to prevent
    accidental truncation of production replay records.

    When ``include_database`` is True (the default), also truncates the
    ``replay_records`` table so that durable persistence tests start from a
    clean state.  Pass ``include_database=False`` to clear only the in-memory
    registry, leaving DB rows intact (useful for testing durability).
    """
    environment = os.environ.get("ENVIRONMENT", "").lower()
    if environment not in _SAFE_ENVIRONMENTS:
        raise RuntimeError(
            f"clear_replay_registry() refuses to run in ENVIRONMENT={environment!r}. "
            "Only 'test', 'development', 'dev', or 'local' environments are permitted. "
            "This function is not safe to call in production."
        )
    with _lock:
        _seen_updates.clear()
    if include_database:
        try:
            with SessionLocal() as db:
                with db.begin():
                    db.execute(delete(ReplayRecord))
        except Exception:
            logger.warning("Failed to clear replay_records table during test cleanup.")
