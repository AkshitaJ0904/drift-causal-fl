"""Start isolated :8001 backend on vapt.db for VAPT testing."""
import os
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

os.environ["DB_USER"] = "dev"
os.environ["DB_PASSWORD"] = "dev"
os.environ["DB_HOST"] = "localhost"
os.environ["DB_NAME"] = "finsentinel_dev"
os.environ["ENVIRONMENT"] = "development"
os.environ.setdefault("FINSENTINEL_ALLOWED_MODEL_VERSIONS", "cnn-v1,resnet-v1,model-v1,demo-v1")
os.environ.setdefault("FINSENTINEL_ALLOWED_ROUNDS", "1,2,3,4,5,6,7,8,9,10")
os.environ.setdefault("FINSENTINEL_MAX_UPDATE_AGE_SECONDS", "86400")
os.environ.setdefault("FINSENTINEL_MAX_FUTURE_CLOCK_SKEW_SECONDS", "300")
os.environ.setdefault("FINSENTINEL_MAX_CONCURRENT_INGESTION", "10")
os.environ.setdefault("FINSENTINEL_INGESTION_RATE_LIMIT_RPM", "60")
os.environ.setdefault("FINSENTINEL_BODY_READ_TIMEOUT_SECONDS", "30")
os.environ.setdefault("FINSENTINEL_SAMPLE_COUNT_TRUST_MODE", "client_claimed")
os.environ.setdefault("FINSENTINEL_HIGH_RISK_ACTION", "pending_approval")

_token_file = Path.home() / ".finsentinel" / "dev_token.txt"
if not _token_file.exists():
    sys.exit("Token file not found")
_token = _token_file.read_text().strip()
os.environ["FINSENTINEL_OPERATOR_TOKEN"] = _token
os.environ["FINSENTINEL_AUDIT_WEBHOOK_TOKEN"] = _token
os.environ["FINSENTINEL_AUDIT_WEBHOOK_URL"] = "http://127.0.0.1:9999/ingest"
os.environ["FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED"] = "1"
os.environ["FINSENTINEL_SIEM_LOG"] = "logs/finsentinel-siem.jsonl"

from sqlalchemy import create_engine  # noqa: E402

_engine = create_engine("sqlite:///vapt.db", connect_args={"check_same_thread": False})
_fake = types.ModuleType("core.supabase.connection")
_fake.engine = _engine  # type: ignore[attr-defined]
sys.modules["core.supabase.connection"] = _fake

import core.supabase.session as _sm  # noqa: E402
from core.supabase.base import Base  # noqa: E402
from db.models.audit_event import AuditEvent  # noqa: E402, F401
from db.models.audit_outbox import AuditOutboxRecord  # noqa: E402, F401
from db.models.replay_record import ReplayRecord  # noqa: E402, F401
from db.models.trusted_key import TrustedKeyRecord  # noqa: E402, F401
from db.models.trusted_model_schema import TrustedModelSchema  # noqa: E402, F401
from db.models.update_approval import UpdateApproval  # noqa: E402, F401

Base.metadata.create_all(_engine)
_sm.SessionLocal.configure(bind=_engine)

import uvicorn  # noqa: E402

print("Starting VAPT isolated backend on http://127.0.0.1:8001 (vapt.db)")
uvicorn.run("app.main:app", host="127.0.0.1", port=8001, reload=False, log_level="warning")
