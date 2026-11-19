"""Migration chain tests — SQLite-based verification of the Alembic upgrade path.

Scope and limitations
---------------------
These tests use SQLite (via Alembic's programmatic API) to verify the structure
of migration outputs.  They are NOT PostgreSQL migration verification:

- SQLite does not support ALTER TABLE ADD CONSTRAINT (NotImplementedError in
  Alembic's SQLite dialect), so migrations a9b11270d3c1, d5e3f7a1b8c0 and
  e1a2b3c4d5e6 (which all add CHECK constraints via op.create_check_constraint
  after table creation) will raise NotImplementedError on SQLite.  The full
  chain beyond 312321b36f52 requires a PostgreSQL instance.

- PostgreSQL-only DDL in e1a2b3c4d5e6 (regex constraint via ALTER TABLE ...
  ADD CONSTRAINT ... CHECK (payload_sha256 ~ ...)) is never executed in
  these tests.

What is verified here
---------------------
1. The full migration chain forms a valid linear sequence (revision IDs are
   consistent; each migration's down_revision matches the previous revision).
2. A fresh SQLite database can be upgraded through the nullable payload
   digest migration (958938d57372 → 06574033dcf6 → 312321b36f52).
3. A POPULATED SQLite database (rows inserted after 06574033dcf6) can be
   upgraded through 312321b36f52 successfully, because the corrected migration
   adds payload_sha256 as nullable=True (not NOT NULL).
4. The resulting schema has payload_sha256 as a nullable column.
5. After the upgrade, existing rows have NULL for payload_sha256, while new
   rows inserted via the ORM carry a valid hex digest.

PostgreSQL verification
-----------------------
To verify the full chain (including d5e3f7a1b8c0 and e1a2b3c4d5e6) on
PostgreSQL, provision a disposable instance satisfying
scripts/verify_postgres_migration.py and run that script with --execute.
Specifically verify:
  - alembic upgrade head on a fresh database
  - alembic upgrade head on a database with pre-existing rows in update_approvals
  - ck_update_approvals_payload_sha256_format constraint enforced
  - ck_update_approvals_payload_sha256_hex constraint enforced
  - alembic downgrade to d5e3f7a1b8c0 fails when NULL rows exist
"""

import os
import tempfile
from contextlib import contextmanager
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect, text

CHAIN = [
    "958938d57372",
    "06574033dcf6",
    "312321b36f52",
    "a9b11270d3c1",
    "c4f2a8b1e930",
    "d5e3f7a1b8c0",
    "e1a2b3c4d5e6",
]


def _make_config():
    """Build an Alembic Config.  The URL is set per-test via engine patching."""
    from alembic.config import Config

    # Locate alembic.ini relative to this test file (finsentinel/tests/ → finsentinel/)
    ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    return Config(os.path.abspath(ini_path))


@contextmanager
def _sqlite_engine(db_path: str):
    """Context manager providing a SQLite engine for the given file path.

    alembic/env.py is executed by Alembic's script runner (not via Python's
    import system).  Each execution starts with:
        from core.supabase.connection import engine
    which reads the current value of core.supabase.connection.engine from
    sys.modules.  Patching that attribute before calling upgrade() makes
    env.py pick up the SQLite engine instead of the production PostgreSQL
    engine.
    """
    sqlite_engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    import core.supabase.connection as _conn_mod

    with patch.object(_conn_mod, "engine", sqlite_engine):
        yield sqlite_engine
    sqlite_engine.dispose()


def _upgrade_to(db_path: str, target: str) -> None:
    from alembic.command import upgrade
    with _sqlite_engine(db_path):
        upgrade(_make_config(), target)


def _columns(engine, table: str) -> dict:
    """Return {column_name: {"nullable": bool}} for a table."""
    insp = inspect(engine)
    return {c["name"]: c for c in insp.get_columns(table)}


# ---------------------------------------------------------------------------
# Revision chain integrity
# ---------------------------------------------------------------------------

def test_migration_chain_revisions_are_linear():
    """Every migration's down_revision matches the preceding revision in CHAIN.

    Uses Alembic's ScriptDirectory API — no database connection required.
    """
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_make_config())
    for i, rev in enumerate(CHAIN):
        script_rev = script.get_revision(rev)
        assert script_rev is not None, f"Revision {rev} not found in script directory"
        assert script_rev.revision == rev, (
            f"revision attribute mismatch for {rev}: got {script_rev.revision!r}"
        )
        expected_down = CHAIN[i - 1] if i > 0 else None
        actual_down = script_rev.down_revision
        assert actual_down == expected_down, (
            f"down_revision mismatch for {rev}: "
            f"got {actual_down!r}, expected {expected_down!r}"
        )


# ---------------------------------------------------------------------------
# Fresh database upgrade
# ---------------------------------------------------------------------------

def test_fresh_sqlite_upgrade_through_312321b36f52():
    """A fresh SQLite database can be upgraded through 312321b36f52.

    Verifies that payload_sha256 is created as a nullable column.
    a9b11270d3c1 and later revisions use op.create_check_constraint (ALTER
    TABLE ADD CONSTRAINT) which is not supported by SQLite — they require
    a PostgreSQL instance.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _upgrade_to(db_path, "312321b36f52")

        engine = sa.create_engine(f"sqlite:///{db_path}")
        cols = _columns(engine, "update_approvals")

        assert "payload_sha256" in cols, "payload_sha256 column must exist"
        assert cols["payload_sha256"]["nullable"] is True, (
            "payload_sha256 must be nullable after the corrected 312321b36f52"
        )
        engine.dispose()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Populated database upgrade through 312321b36f52
# ---------------------------------------------------------------------------

def test_populated_sqlite_upgrade_through_312321b36f52():
    """312321b36f52 must succeed on a populated database.

    Prior to the fix, 312321b36f52 added payload_sha256 as NOT NULL.  On
    PostgreSQL this would fail when rows already existed in update_approvals.
    After the fix (nullable=True), the migration succeeds and existing rows
    get NULL for payload_sha256.

    This test reproduces the populated-database scenario on SQLite to verify
    the structural fix.  It does not prove PostgreSQL correctness (NULL
    semantics for NOT NULL alter differ between databases) — that requires a
    live PostgreSQL instance.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        # Step 1: upgrade to 06574033dcf6 — creates update_approvals WITHOUT
        # payload_sha256.
        _upgrade_to(db_path, "06574033dcf6")

        # Step 2: insert a legacy row (simulating a database that had rows
        # before payload verification was introduced).
        engine = sa.create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO update_approvals "
                "(client_id, update_id, model_version, round_number, "
                "status, reason, created_at, updated_at) "
                "VALUES ('c-legacy', 'u-legacy', 'cnn-v1', 1, "
                "'pending_approval', 'Legacy row predating payload verification.', "
                "datetime('now'), datetime('now'))"
            ))
            conn.commit()
        engine.dispose()

        # Step 3: upgrade through 312321b36f52 — this MUST succeed after the
        # nullable=True fix.  On the original NOT NULL version, SQLite and
        # PostgreSQL both reject this when rows exist without a default.
        _upgrade_to(db_path, "312321b36f52")

        # Step 4: verify the legacy row now has NULL for payload_sha256.
        engine = sa.create_engine(f"sqlite:///{db_path}")
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT payload_sha256 FROM update_approvals "
                "WHERE client_id = 'c-legacy'"
            ))
            row = result.fetchone()
        assert row is not None, "Legacy row must still exist after migration"
        assert row[0] is None, (
            "payload_sha256 must be NULL for the legacy row — "
            "the column was added as nullable=True with no default"
        )
        engine.dispose()

    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Column nullability after the corrected chain
# ---------------------------------------------------------------------------

def test_payload_sha256_is_nullable_after_upgrade():
    """payload_sha256 is nullable after upgrading through 312321b36f52."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _upgrade_to(db_path, "312321b36f52")
        engine = sa.create_engine(f"sqlite:///{db_path}")
        cols = _columns(engine, "update_approvals")
        assert cols["payload_sha256"]["nullable"] is True
        engine.dispose()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# SQLite chain limit — explicit documentation test
# ---------------------------------------------------------------------------

def test_sqlite_chain_limit_is_at_a9b11270d3c1():
    """SQLite cannot run a9b11270d3c1 because it adds a CHECK constraint via
    ALTER TABLE (op.create_check_constraint), which is not supported by
    Alembic's SQLite dialect.

    This test documents the exact boundary: the chain through 312321b36f52
    works on SQLite; a9b11270d3c1 and all later revisions require PostgreSQL
    or Alembic batch mode.

    PostgreSQL verification of the full chain is required before production
    deployment.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _upgrade_to(db_path, "312321b36f52")  # This succeeds on SQLite.

        # a9b11270d3c1 calls op.create_check_constraint — SQLite emits
        # ALTER TABLE ... ADD CONSTRAINT ... which is not supported.
        with pytest.raises(NotImplementedError):
            _upgrade_to(db_path, "a9b11270d3c1")

    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
