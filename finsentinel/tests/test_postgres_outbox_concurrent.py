"""Concurrent outbox claiming tests against a real PostgreSQL database.

These tests verify SELECT FOR UPDATE SKIP LOCKED behaviour that cannot be
exercised on SQLite.  They are **opt-in** and require:

    FINSENTINEL_POSTGRES_TEST=1
    PG_MIGRATION_TEST_PASSWORD=<password for finsentinel_migration_test role>

Both variables must be set; otherwise every test in this module is skipped.

The tests use a dedicated test database (finsentinel_migration_test) and
clean up after themselves.  They never touch the production database.
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Skip guard — must come before any imports that touch the PG engine
# ---------------------------------------------------------------------------

_PG_ENABLED = os.environ.get("FINSENTINEL_POSTGRES_TEST", "").strip() == "1"
_PG_PASSWORD = os.environ.get("PG_MIGRATION_TEST_PASSWORD", "").strip()

pytestmark = pytest.mark.skipif(
    not (_PG_ENABLED and _PG_PASSWORD),
    reason=(
        "PostgreSQL concurrent tests skipped. "
        "Set FINSENTINEL_POSTGRES_TEST=1 and PG_MIGRATION_TEST_PASSWORD=<pw> to enable."
    ),
)

# ---------------------------------------------------------------------------
# Engine / session factory (bypasses conftest.py SQLite override)
# ---------------------------------------------------------------------------

_PG_URL = (
    f"postgresql+psycopg://finsentinel_migration_test:{_PG_PASSWORD}"
    "@localhost:5432/finsentinel_migration_test?sslmode=require"
)

# Engine is created lazily so the module can be collected even when skipped.
_pg_engine = None
_PgSession: Any = None


def _get_session_factory():
    global _pg_engine, _PgSession
    if _pg_engine is None:
        _pg_engine = create_engine(_PG_URL, pool_size=5, max_overflow=0)
        _PgSession = sessionmaker(
            bind=_pg_engine,
            autoflush=False,
            expire_on_commit=False,
        )
    return _PgSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enqueue_records(n: int) -> list[int]:
    """Insert *n* pending outbox records directly; return their IDs."""
    from db.models.audit_outbox import AuditOutboxRecord  # noqa: PLC0415

    PgSession = _get_session_factory()
    ids: list[int] = []
    with PgSession() as db:
        with db.begin():
            for i in range(n):
                rec = AuditOutboxRecord(
                    idempotency_key=uuid.uuid4().hex,
                    event_id=None,
                    event_type="test.concurrent",
                    severity="low",
                    description=f"concurrent test record {i}",
                    client_id="cl-concurrent",
                    update_id=f"u-{i}",
                    status="pending",
                    attempt_count=0,
                    claimed_until=None,
                    delivered_at=None,
                )
                db.add(rec)
                db.flush()
                ids.append(rec.id)
    return ids


def _delete_records(ids: list[int]) -> None:
    """Remove test records by ID."""
    from db.models.audit_outbox import AuditOutboxRecord  # noqa: PLC0415

    PgSession = _get_session_factory()
    with PgSession() as db:
        with db.begin():
            db.execute(
                delete(AuditOutboxRecord).where(AuditOutboxRecord.id.in_(ids))
            )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _pg_clean_outbox():
    """Truncate the PG outbox table before and after each test.

    The test database may contain leftover rows from prior migration runs.
    A clean slate ensures the claim queries only see records created by the
    current test and that IDs match expectations.
    """
    from sqlalchemy import delete as sa_delete

    from db.models.audit_outbox import AuditOutboxRecord  # noqa: PLC0415

    PgSession = _get_session_factory()

    def _truncate() -> None:
        with PgSession() as db:
            with db.begin():
                db.execute(sa_delete(AuditOutboxRecord))

    _truncate()
    yield
    _truncate()


# ---------------------------------------------------------------------------
# Test 1 — No double-claiming under concurrency
# ---------------------------------------------------------------------------


def test_no_double_claiming_with_two_concurrent_workers():
    """Two workers starting simultaneously must never claim the same record.

    SELECT FOR UPDATE SKIP LOCKED guarantees this on PostgreSQL.  The test
    enqueues N records, starts two threads with a Barrier so they hit the
    claim query at the same time, and asserts that the union of their claimed
    IDs is exactly the full set (no overlap, no loss).
    """
    from audit.outbox import claim_pending_batch  # noqa: PLC0415

    N = 10
    record_ids = _enqueue_records(N)

    barrier = threading.Barrier(2)
    results: dict[int, list[int]] = {0: [], 1: []}
    errors: list[Exception] = []
    PgSession = _get_session_factory()

    def _worker(worker_id: int) -> None:
        try:
            with PgSession() as db:
                barrier.wait(timeout=5.0)  # synchronised start
                with db.begin():
                    claimed = claim_pending_batch(db, limit=N)
                    results[worker_id] = [r.id for r in claimed]
        except Exception as exc:
            errors.append(exc)

    t0 = threading.Thread(target=_worker, args=(0,))
    t1 = threading.Thread(target=_worker, args=(1,))
    t0.start()
    t1.start()
    t0.join(timeout=10.0)
    t1.join(timeout=10.0)

    assert not errors, f"Worker thread raised: {errors}"
    all_claimed = results[0] + results[1]
    assert set(all_claimed) == set(record_ids), (
        f"Some records were lost or unclaimed. "
        f"expected={sorted(record_ids)} "
        f"worker0={sorted(results[0])} worker1={sorted(results[1])}"
    )
    assert len(all_claimed) == N, (
        f"Double-claiming detected: total claimed={len(all_claimed)} but only {N} records. "
        f"worker0={sorted(results[0])} worker1={sorted(results[1])}"
    )
    # No record appears in both workers' lists
    overlap = set(results[0]) & set(results[1])
    assert not overlap, f"Records claimed by both workers: {overlap}"


# ---------------------------------------------------------------------------
# Test 2 — Expired claim is recovered by a second worker
# ---------------------------------------------------------------------------


def test_expired_claim_recovered_by_second_worker():
    """A claimed record whose claimed_until is in the past must be reclaimable.

    This validates that a crashed worker's held records do not vanish silently.
    """
    from audit.outbox import claim_pending_batch  # noqa: PLC0415
    from db.models.audit_outbox import AuditOutboxRecord  # noqa: PLC0415

    PgSession = _get_session_factory()

    # Insert a record already in 'claimed' state with an expired deadline
    expired_until = datetime.now(tz=UTC) - timedelta(seconds=120)
    record_id: int | None = None

    with PgSession() as db:
        with db.begin():
            rec = AuditOutboxRecord(
                idempotency_key=uuid.uuid4().hex,
                event_id=None,
                event_type="test.expired_claim",
                severity="low",
                description="expired claim recovery test",
                client_id="cl-expired",
                update_id="u-expired",
                status="claimed",          # simulates a crashed worker
                attempt_count=1,
                claimed_until=expired_until,
                delivered_at=None,
            )
            db.add(rec)
            db.flush()
            record_id = rec.id

    # A fresh worker must be able to claim this expired record
    with PgSession() as db:
        with db.begin():
            claimed = claim_pending_batch(db, limit=10)
            claimed_ids = [r.id for r in claimed]

    assert record_id in claimed_ids, (
        f"Expired claimed record (id={record_id}) was not recovered by a second worker."
    )


# ---------------------------------------------------------------------------
# Test 3 — No silent loss: all pending records are eventually claimed
# ---------------------------------------------------------------------------


def test_no_silent_loss_all_records_claimed():
    """Every enqueued pending record must be claimable; none silently disappear."""
    from audit.outbox import claim_pending_batch  # noqa: PLC0415

    N = 5
    record_ids = _enqueue_records(N)
    PgSession = _get_session_factory()

    claimed_ids: list[int] = []
    with PgSession() as db:
        with db.begin():
            claimed = claim_pending_batch(db, limit=N)
            claimed_ids = [r.id for r in claimed]

    missing = set(record_ids) - set(claimed_ids)
    assert not missing, (
        f"Records were silently lost (not reclaimable): {missing}"
    )
    assert len(claimed_ids) == N, (
        f"Expected {N} records claimed; got {len(claimed_ids)}"
    )
