"""FinSentinel local development server launcher.

Starts the FastAPI backend on http://localhost:8000 using an in-file SQLite
database.  No PostgreSQL credentials or psycopg driver required.

Usage (run from the finsentinel/ directory):
    .\\venv-security\\Scripts\\python.exe scripts\\run_dev.py

The operator token is printed at startup and saved to dev_token.txt in the
finsentinel/ directory.  Open that file and paste the token into the browser
login page at http://localhost:5173 (or whichever port Vite picks).
"""

import os
import secrets
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Env vars — MUST be set before any finsentinel module is imported.
# ---------------------------------------------------------------------------
os.environ.setdefault("DB_USER", "dev")
os.environ.setdefault("DB_PASSWORD", "dev")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "finsentinel_dev")

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("LOG_LEVEL", "INFO")

os.environ.setdefault("FINSENTINEL_ALLOWED_MODEL_VERSIONS", "cnn-v1,resnet-v1,model-v1,demo-v1")
os.environ.setdefault("FINSENTINEL_ALLOWED_ROUNDS", "1,2,3,4,5,6,7,8,9,10")
os.environ.setdefault("FINSENTINEL_MAX_UPDATE_AGE_SECONDS", "86400")
os.environ.setdefault("FINSENTINEL_MAX_FUTURE_CLOCK_SKEW_SECONDS", "300")
os.environ.setdefault("FINSENTINEL_MAX_CONCURRENT_INGESTION", "10")
os.environ.setdefault("FINSENTINEL_INGESTION_RATE_LIMIT_RPM", "60")
os.environ.setdefault("FINSENTINEL_BODY_READ_TIMEOUT_SECONDS", "30")
os.environ.setdefault("FINSENTINEL_SAMPLE_COUNT_TRUST_MODE", "client_claimed")
os.environ.setdefault("FINSENTINEL_HIGH_RISK_ACTION", "quarantined")

# ---------------------------------------------------------------------------
# 2. Operator token — generate once, persist outside the repo so it is never
#    accidentally committed.  Location: %USERPROFILE%\.finsentinel\dev_token.txt
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
_TOKEN_DIR = Path.home() / ".finsentinel"
_TOKEN_DIR.mkdir(exist_ok=True)
TOKEN_FILE = _TOKEN_DIR / "dev_token.txt"

if TOKEN_FILE.exists():
    _existing = TOKEN_FILE.read_text().strip()
    token = _existing if len(_existing) >= 32 else secrets.token_hex(32)
    if len(_existing) < 32:
        TOKEN_FILE.write_text(token)
else:
    token = secrets.token_hex(32)
    TOKEN_FILE.write_text(token)

os.environ["FINSENTINEL_OPERATOR_TOKEN"] = token

# ---------------------------------------------------------------------------
# 3. Create SQLite engine BEFORE importing any finsentinel module.
#    Then inject a fake core.supabase.connection so psycopg (the PostgreSQL
#    driver) is never loaded — it is blocked by Application Control policy.
# ---------------------------------------------------------------------------
from sqlalchemy import create_engine  # noqa: E402  (pure SQLAlchemy, no driver)

DB_FILE = REPO_ROOT / "finsentinel_dev.db"
_sqlite_engine = create_engine(
    f"sqlite:///{DB_FILE}",
    connect_args={"check_same_thread": False},
)

# Replace the real connection module with a lightweight stub that exposes the
# SQLite engine under the same attribute name the rest of the code expects.
_fake_conn = types.ModuleType("core.supabase.connection")
_fake_conn.engine = _sqlite_engine  # type: ignore[attr-defined]
sys.modules["core.supabase.connection"] = _fake_conn

# ---------------------------------------------------------------------------
# 4. Now it is safe to import finsentinel internals.
# ---------------------------------------------------------------------------
import core.supabase.session as _session_module  # noqa: E402
from core.supabase.base import Base  # noqa: E402

# Import every model so its table is registered with Base.metadata
from db.models.audit_event import AuditEvent  # noqa: E402, F401
from db.models.audit_outbox import AuditOutboxRecord  # noqa: E402, F401
from db.models.replay_record import ReplayRecord  # noqa: E402, F401
from db.models.trusted_key import TrustedKeyRecord  # noqa: E402, F401
from db.models.trusted_model_schema import TrustedModelSchema  # noqa: E402, F401
from db.models.update_approval import UpdateApproval  # noqa: E402, F401

Base.metadata.create_all(_sqlite_engine)
_session_module.SessionLocal.configure(bind=_sqlite_engine)

# ---------------------------------------------------------------------------
# 5. Startup banner
# ---------------------------------------------------------------------------
SEP = "=" * 64
print(SEP)
print("  FinSentinel  —  Development Server")
print(SEP)
print(f"  Database : SQLite  ({DB_FILE.name})")
print("  Backend  : http://localhost:8000")
print("  Frontend : http://localhost:5173  (start separately)")
print()
print(f"  Token file : {TOKEN_FILE}")
print("  Open that file and paste the token into the login page.")
print(SEP)

import uvicorn  # noqa: E402

uvicorn.run(
    "app.main:app",
    host="127.0.0.1",
    port=8000,
    reload=False,
    log_level="info",
)
