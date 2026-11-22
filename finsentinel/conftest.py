"""Process-local SQLite test database bootstrap for FinSentinel.

Sets placeholder database environment variables at import time so that
core.supabase.connection can construct a URL (lazy engine, never connected).
A session-scoped fixture then reconfigures SessionLocal to use an in-memory
SQLite database before any test uses it.

This file must remain at the finsentinel/ root (next to pyproject.toml) so
pytest loads it before collecting or importing test files.
"""

import os

# Set placeholder DB credentials before connection.py is imported.
# These allow Settings.database_url to construct a URL; the PostgreSQL engine
# is lazy and never connects because SessionLocal is redirected to SQLite below.
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "finsentinel_test")
# Use test environment so get_detection_config() provides fallback thresholds.
os.environ.setdefault("ENVIRONMENT", "test")
# Required by ModelUpdatePolicy.__post_init__; must be non-empty frozensets.
# Values match the model version and round number used by the ingestion API tests.
os.environ.setdefault("FINSENTINEL_ALLOWED_MODEL_VERSIONS", "cnn-v1")
os.environ.setdefault("FINSENTINEL_ALLOWED_ROUNDS", "1")
# The ingestion API tests use a fixed created_at of 2026-10-21T10:00:00Z.
# Set a large window so the timestamp check never rejects test envelopes.
os.environ.setdefault("FINSENTINEL_MAX_UPDATE_AGE_SECONDS", "99999999")

import pytest
import sqlalchemy as _sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# core.supabase.connection calls create_engine() at module level with a
# PostgreSQL URL.  On this machine the psycopg DLL is blocked by Application
# Control Policy, so we intercept create_engine before that import and return
# a None placeholder for PostgreSQL URLs.  The real module (with its real
# create_database_engine/get_settings functions) is imported normally so that
# test_database_timeouts can still patch and call it.  The fixture below
# redirects SessionLocal to the in-memory SQLite engine before any test runs.
_real_create_engine = _sqlalchemy.create_engine


def _safe_create_engine(url, **kwargs):  # type: ignore[no-untyped-def]
    if str(url).startswith("postgresql"):
        return None
    return _real_create_engine(url, **kwargs)


_sqlalchemy.create_engine = _safe_create_engine  # type: ignore[method-assign]
try:
    import core.supabase.connection as _conn_module  # noqa: F401
finally:
    _sqlalchemy.create_engine = _real_create_engine  # restore immediately

import core.supabase.session as _session_module  # noqa: E402
from core.supabase.base import Base  # noqa: E402

# Import all model modules so their classes are registered with Base.metadata
# before create_all is called.
from db.models.audit_event import AuditEvent  # noqa: E402, F401
from db.models.audit_outbox import AuditOutboxRecord  # noqa: E402, F401
from db.models.replay_record import ReplayRecord  # noqa: E402, F401
from db.models.trusted_key import TrustedKeyRecord  # noqa: E402, F401
from db.models.trusted_model_schema import TrustedModelSchema  # noqa: E402, F401
from db.models.update_approval import UpdateApproval  # noqa: E402, F401


@pytest.fixture(scope="session", autouse=True)
def _sqlite_test_database():
    """Redirect SessionLocal to a process-local in-memory SQLite database.

    Uses StaticPool so all sessions share one connection, keeping the
    in-memory database intact across the test session.  The PostgreSQL engine
    created by connection.py at import time is never used.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    _session_module.SessionLocal.configure(bind=engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
