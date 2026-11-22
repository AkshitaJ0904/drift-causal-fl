"""Seed the SQLite dev database with demo trusted keys and model schemas.

Run AFTER run_dev.py has started (the db file must exist).

Usage (from finsentinel/ directory):
    .\\venv-security\\Scripts\\python.exe scripts\\seed_demo_data.py
"""

import os
import sys
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Same env-var setup as run_dev.py
os.environ.setdefault("DB_USER", "dev")
os.environ.setdefault("DB_PASSWORD", "dev")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "finsentinel_dev")
os.environ.setdefault("ENVIRONMENT", "development")

# Point at the same persistent SQLite file
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

DB_FILE = REPO_ROOT / "finsentinel_dev.db"

_sqlite_engine = create_engine(
    f"sqlite:///{DB_FILE}",
    connect_args={"check_same_thread": False},
)

# Inject fake connection module so psycopg is never touched
_fake_conn = types.ModuleType("core.supabase.connection")
_fake_conn.engine = _sqlite_engine  # type: ignore[attr-defined]
sys.modules["core.supabase.connection"] = _fake_conn

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402

import core.supabase.session as _session_module  # noqa: E402
from core.supabase.base import Base  # noqa: E402
from db.models.trusted_key import TrustedKeyRecord  # noqa: E402
from db.models.trusted_model_schema import TrustedModelSchema  # noqa: E402

Base.metadata.create_all(_sqlite_engine)
_session_module.SessionLocal.configure(bind=_sqlite_engine)

def _gen_pem():
    priv = Ed25519PrivateKey.generate()
    return priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()

DEMO_KEYS: list[dict[str, Any]] = [
    {"key_id": "demo-key-client-1", "client_id": "demo-client-1", "max_sample_count": 1000},
    {"key_id": "demo-key-client-2", "client_id": "demo-client-2", "max_sample_count": 500},
    {"key_id": "demo-key-client-3", "client_id": "demo-client-3", "max_sample_count": None},
]

DEMO_SCHEMAS: list[dict[str, Any]] = [
    {
        "model_version": "cnn-v1",
        "tensor_specs": {
            "conv1.weight": [[8, 1, 3, 3], "torch.float32"],
            "conv1.bias":   [[8], "torch.float32"],
            "conv2.weight": [[16, 8, 3, 3], "torch.float32"],
            "conv2.bias":   [[16], "torch.float32"],
            "fc1.weight":   [[128, 400], "torch.float32"],
            "fc1.bias":     [[128], "torch.float32"],
            "fc2.weight":   [[10, 128], "torch.float32"],
            "fc2.bias":     [[10], "torch.float32"],
        },
    },
    {
        "model_version": "demo-v1",
        "tensor_specs": {
            "layer1.weight": [[64, 32], "torch.float32"],
            "layer1.bias":   [[64], "torch.float32"],
            "layer2.weight": [[10, 64], "torch.float32"],
            "layer2.bias":   [[10], "torch.float32"],
        },
    },
]

with Session(_sqlite_engine) as db:
    # Trusted keys
    for kd in DEMO_KEYS:
        exists = db.query(TrustedKeyRecord).filter_by(key_id=kd["key_id"]).first()
        if exists:
            print(f"  key already exists: {kd['key_id']}")
            continue
        db.add(TrustedKeyRecord(
            key_id=kd["key_id"],
            client_id=kd["client_id"],
            public_key_pem=_gen_pem(),
            max_sample_count=kd["max_sample_count"],
            is_active=True,
        ))
        print(f"  registered key: {kd['key_id']}  ({kd['client_id']})")

    # Model schemas
    for sd in DEMO_SCHEMAS:
        exists_schema = (
            db.query(TrustedModelSchema).filter_by(model_version=sd["model_version"]).first()
        )
        if exists_schema:
            print(f"  schema already exists: {sd['model_version']}")
            continue
        db.add(TrustedModelSchema(
            model_version=sd["model_version"],
            tensor_specs=sd["tensor_specs"],
        ))
        print(f"  registered schema: {sd['model_version']}")

    db.commit()

print()
print("Seed complete. Refresh the browser to see updated counts.")
