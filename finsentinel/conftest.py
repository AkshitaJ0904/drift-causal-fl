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
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import core.supabase.session as _session_module
from core.supabase.base import Base

# Import all model modules so their classes are registered with Base.metadata
# before create_all is called.
from db.models.audit_event import AuditEvent  # noqa: F401
from db.models.audit_outbox import AuditOutboxRecord  # noqa: F401
from db.models.replay_record import ReplayRecord  # noqa: F401
from db.models.trusted_key import TrustedKeyRecord  # noqa: F401
from db.models.trusted_model_schema import TrustedModelSchema  # noqa: F401
from db.models.update_approval import UpdateApproval  # noqa: F401


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
