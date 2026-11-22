"""FinSentinel E2E demo: submit 6 test cases + 3 extras for browser testing.

USAGE (from the finsentinel/ directory, with backend running on :8000):
    .\\venv-security\\Scripts\\python.exe scripts\\demo_submit_updates.py

Produces scripts/demo_payloads.json — payload bytes for the aggregation test.
Private keys are generated fresh each run and are NEVER written to disk.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import types
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# 0.  Sys.modules injection + SQLite setup (must precede all finsentinel imports)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DB_USER", "dev")
os.environ.setdefault("DB_PASSWORD", "dev")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "finsentinel_dev")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("FINSENTINEL_ALLOWED_MODEL_VERSIONS", "cnn-v1,resnet-v1,model-v1,demo-v1")
os.environ.setdefault("FINSENTINEL_ALLOWED_ROUNDS", "1,2,3,4,5,6,7,8,9,10")
os.environ.setdefault("FINSENTINEL_MAX_UPDATE_AGE_SECONDS", "86400")
os.environ.setdefault("FINSENTINEL_SAMPLE_COUNT_TRUST_MODE", "client_claimed")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

DB_FILE = REPO_ROOT / "finsentinel_dev.db"
_sqlite_engine = create_engine(
    f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False}
)

_fake_conn = types.ModuleType("core.supabase.connection")
_fake_conn.engine = _sqlite_engine  # type: ignore[attr-defined]
sys.modules["core.supabase.connection"] = _fake_conn

import core.supabase.session as _session_module  # noqa: E402
from core.crypto import sign_envelope  # noqa: E402
from core.supabase.base import Base  # noqa: E402
from db.models.trusted_key import TrustedKeyRecord  # noqa: E402
from ingestion.schemas import UpdateEnvelope  # noqa: E402

Base.metadata.create_all(_sqlite_engine)
_session_module.SessionLocal.configure(bind=_sqlite_engine)

import torch  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402

from core.model_registry import register_model_schema  # noqa: E402

# ---------------------------------------------------------------------------
# 1.  Ensure cnn-v1 schema is registered with correct torch dtype strings
#     (seed_demo_data.py stored "float32"; the validator needs "torch.float32")
# ---------------------------------------------------------------------------
_CNN_V1_REF: dict[str, torch.Tensor] = {
    "conv1.weight": torch.zeros(8, 1, 3, 3),
    "conv1.bias":   torch.zeros(8),
    "conv2.weight": torch.zeros(16, 8, 3, 3),
    "conv2.bias":   torch.zeros(16),
    "fc1.weight":   torch.zeros(128, 400),
    "fc1.bias":     torch.zeros(128),
    "fc2.weight":   torch.zeros(10, 128),
    "fc2.bias":     torch.zeros(10),
}
register_model_schema("cnn-v1", _CNN_V1_REF)
print("[setup] cnn-v1 schema registered/updated (dtype=torch.float32)")

# ---------------------------------------------------------------------------
# 2.  Generate Ed25519 key pairs — private keys stay in memory only
# ---------------------------------------------------------------------------
def _gen_keypair() -> tuple[Ed25519PrivateKey, str]:
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return priv, pub_pem


priv1, pub_pem1 = _gen_keypair()
priv2, pub_pem2 = _gen_keypair()
priv_unregistered, _ = _gen_keypair()  # never registered → used for case f

with Session(_sqlite_engine) as db:
    for key_id, client_id, pub_pem, max_sc in [
        ("submit-key-1", "submit-client-1", pub_pem1, 1000),
        ("submit-key-2", "submit-client-2", pub_pem2, 500),
    ]:
        existing = db.query(TrustedKeyRecord).filter_by(key_id=key_id).first()
        if existing:
            db.delete(existing)
            db.flush()
        db.add(TrustedKeyRecord(
            key_id=key_id,
            client_id=client_id,
            public_key_pem=pub_pem,
            max_sample_count=max_sc,
            is_active=True,
        ))
        print(f"[setup] registered key: {key_id}  ({client_id})")
    db.commit()
print()

# ---------------------------------------------------------------------------
# 3.  NPZ payload builder (replicates finsentinel's serialization format)
#     Uses numpy only — no torch import needed in this helper.
# ---------------------------------------------------------------------------
def _make_payload(state_dict: dict[str, np.ndarray]) -> bytes:
    arrays: dict[str, np.ndarray] = {}
    manifest_tensors = []
    for i, (name, arr) in enumerate(state_dict.items()):
        key = f"tensor_{i:06d}"
        arrays[key] = arr
        manifest_tensors.append({
            "archive_key": key,
            "dtype": arr.dtype.str,
            "name": name,
            "shape": list(arr.shape),
        })
    manifest = {
        "format_version": 1,
        "tensor_count": len(manifest_tensors),
        "tensors": manifest_tensors,
    }
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    arrays["__manifest__"] = np.frombuffer(manifest_bytes, dtype=np.uint8)
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)  # type: ignore[arg-type]
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 4.  State dict factories
# ---------------------------------------------------------------------------
def _cnn_v1_clean(seed: int = 42) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    return {
        "conv1.weight": rng.standard_normal((8, 1, 3, 3)).astype(np.float32) * 0.05,
        "conv1.bias":   np.zeros(8, dtype=np.float32),
        "conv2.weight": rng.standard_normal((16, 8, 3, 3)).astype(np.float32) * 0.05,
        "conv2.bias":   np.zeros(16, dtype=np.float32),
        "fc1.weight":   rng.standard_normal((128, 400)).astype(np.float32) * 0.05,
        "fc1.bias":     np.zeros(128, dtype=np.float32),
        "fc2.weight":   rng.standard_normal((10, 128)).astype(np.float32) * 0.05,
        "fc2.bias":     np.zeros(10, dtype=np.float32),
    }


def _cnn_v1_huge_weights() -> dict[str, np.ndarray]:
    """abs_mean ≈ 50 >> threshold 10 → HIGH risk → quarantined."""
    rng = np.random.default_rng(99)
    return {
        "conv1.weight": rng.standard_normal((8, 1, 3, 3)).astype(np.float32) * 50.0,
        "conv1.bias":   np.zeros(8, dtype=np.float32),
        "conv2.weight": rng.standard_normal((16, 8, 3, 3)).astype(np.float32) * 50.0,
        "conv2.bias":   np.zeros(16, dtype=np.float32),
        "fc1.weight":   rng.standard_normal((128, 400)).astype(np.float32) * 50.0,
        "fc1.bias":     np.zeros(128, dtype=np.float32),
        "fc2.weight":   rng.standard_normal((10, 128)).astype(np.float32) * 50.0,
        "fc2.bias":     np.zeros(10, dtype=np.float32),
    }


def _cnn_v1_wrong_shape() -> dict[str, np.ndarray]:
    """fc1.weight is (128, 100) instead of (128, 400) → schema rejection."""
    rng = np.random.default_rng(42)
    return {
        "conv1.weight": rng.standard_normal((8, 1, 3, 3)).astype(np.float32) * 0.05,
        "conv1.bias":   np.zeros(8, dtype=np.float32),
        "conv2.weight": rng.standard_normal((16, 8, 3, 3)).astype(np.float32) * 0.05,
        "conv2.bias":   np.zeros(16, dtype=np.float32),
        "fc1.weight":   rng.standard_normal((128, 100)).astype(np.float32) * 0.05,  # WRONG
        "fc1.bias":     np.zeros(128, dtype=np.float32),
        "fc2.weight":   rng.standard_normal((10, 128)).astype(np.float32) * 0.05,
        "fc2.bias":     np.zeros(10, dtype=np.float32),
    }


# ---------------------------------------------------------------------------
# 5.  Envelope + signing helpers
# ---------------------------------------------------------------------------
API_URL = "http://localhost:8000/api/v1/updates"


def _build_body(
    *,
    client_id: str,
    key_id: str,
    private_key: Ed25519PrivateKey,
    model_version: str,
    round_number: int,
    sample_count: int,
    state_dict: dict[str, np.ndarray],
    tamper_sha: bool = False,
    override_update_id: str | None = None,
) -> tuple[dict, str, bytes]:
    """Return (body_dict, update_id, raw_payload_bytes)."""
    payload_bytes = _make_payload(state_dict)
    real_sha = hashlib.sha256(payload_bytes).hexdigest()

    if tamper_sha:
        last = real_sha[-1]
        sha_to_use = real_sha[:-1] + ("a" if last != "a" else "b")
    else:
        sha_to_use = real_sha

    update_id = override_update_id or str(uuid.uuid4())
    now = datetime.now(UTC)

    env_base = {
        "update_id": update_id,
        "client_id": client_id,
        "model_version": model_version,
        "round_number": round_number,
        "sample_count": sample_count,
        "payload_sha256": sha_to_use,
        "payload_size_bytes": len(payload_bytes),
        "created_at": now.isoformat(),
        "signature": "PENDING",  # placeholder; excluded from canonical signed data
        "signing_key_id": key_id,
    }
    envelope = UpdateEnvelope(**env_base)  # type: ignore[arg-type]
    signed = sign_envelope(envelope, private_key)
    envelope = UpdateEnvelope(**{**env_base, "signature": signed})  # type: ignore[arg-type]

    body = {
        "envelope": envelope.model_dump(mode="json"),
        "payload_base64": base64.b64encode(payload_bytes).decode(),
    }
    return body, update_id, payload_bytes


def _post(body: dict) -> tuple[int, dict | str]:
    data = json.dumps(body, default=str).encode()
    req = urllib.request.Request(
        API_URL, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            try:
                return resp.getcode(), json.loads(raw)
            except json.JSONDecodeError:
                return resp.getcode(), raw.decode()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw.decode()


# ---------------------------------------------------------------------------
# 6.  Run all cases
# ---------------------------------------------------------------------------
SEP = "=" * 72
print(SEP)
print("  FinSentinel E2E Demo — 6 cases + 3 extras for browser testing")
print(SEP)

payloads_for_aggregation: dict[str, dict] = {}  # update_id → metadata

# ── Case a: clean update ───────────────────────────────────────────────────
print("\n[a] Clean update (cnn-v1, round 1, submit-client-1)")
print("    expected: HTTP 200, status=pending_approval (LOW risk)")
body_a, uid_a, raw_a = _build_body(
    client_id="submit-client-1", key_id="submit-key-1", private_key=priv1,
    model_version="cnn-v1", round_number=1, sample_count=100,
    state_dict=_cnn_v1_clean(42),
)
sc_a, resp_a = _post(body_a)
status_a = resp_a.get("status") if isinstance(resp_a, dict) else "?"
print(f"    → HTTP {sc_a}  status={status_a}  update_id={uid_a}")
if sc_a == 200:
    payloads_for_aggregation[uid_a] = {
        "client_id": "submit-client-1",
        "model_version": "cnn-v1",
        "round_number": 1,
        "sample_count": 100,
        "payload_base64": body_a["payload_base64"],
    }

# ── Case b: huge weights ───────────────────────────────────────────────────
print("\n[b] Huge weights (abs_mean≈50 >> threshold 10, submit-client-2)")
print("    expected: HTTP 200, status=quarantined (HIGH risk — not in Approvals page)")
body_b, uid_b, raw_b = _build_body(
    client_id="submit-client-2", key_id="submit-key-2", private_key=priv2,
    model_version="cnn-v1", round_number=2, sample_count=50,
    state_dict=_cnn_v1_huge_weights(),
)
sc_b, resp_b = _post(body_b)
status_b = resp_b.get("status") if isinstance(resp_b, dict) else "?"
print(f"    → HTTP {sc_b}  status={status_b}  update_id={uid_b}")

# ── Case c: replay attack ──────────────────────────────────────────────────
print("\n[c] Replay attack (re-submit case a body verbatim)")
print("    expected: HTTP 409")
sc_c, resp_c = _post(body_a)
detail_c = resp_c.get("detail") if isinstance(resp_c, dict) else resp_c
print(f"    → HTTP {sc_c}  detail={detail_c!r}")

# ── Case d: tampered SHA-256 ───────────────────────────────────────────────
print("\n[d] Tampered payload SHA-256")
print("    expected: HTTP 422")
body_d, uid_d, _ = _build_body(  # type: ignore[assignment]
    client_id="submit-client-1", key_id="submit-key-1", private_key=priv1,
    model_version="cnn-v1", round_number=5, sample_count=80,
    state_dict=_cnn_v1_clean(43),
    tamper_sha=True,
)
sc_d, resp_d = _post(body_d)
detail_d = resp_d.get("detail") if isinstance(resp_d, dict) else resp_d
print(f"    → HTTP {sc_d}  detail={detail_d!r}")

# ── Case e: wrong schema (fc1.weight shape mismatch) ──────────────────────
print("\n[e] Wrong schema — fc1.weight (128,100) vs registered (128,400)")
print("    expected: HTTP 422")
body_e, uid_e, _ = _build_body(  # type: ignore[assignment]
    client_id="submit-client-1", key_id="submit-key-1", private_key=priv1,
    model_version="cnn-v1", round_number=6, sample_count=80,
    state_dict=_cnn_v1_wrong_shape(),
)
sc_e, resp_e = _post(body_e)
detail_e = resp_e.get("detail") if isinstance(resp_e, dict) else resp_e
print(f"    → HTTP {sc_e}  detail={detail_e!r}")

# ── Case f: unregistered signing key ──────────────────────────────────────
print("\n[f] Unregistered signing key (key_id=unregistered-key-999)")
print("    expected: HTTP 401")
body_f, uid_f, _ = _build_body(  # type: ignore[assignment]
    client_id="submit-client-1", key_id="unregistered-key-999",
    private_key=priv_unregistered,
    model_version="cnn-v1", round_number=7, sample_count=80,
    state_dict=_cnn_v1_clean(44),
)
sc_f, resp_f = _post(body_f)
detail_f = resp_f.get("detail") if isinstance(resp_f, dict) else resp_f
print(f"    → HTTP {sc_f}  detail={detail_f!r}")

# ── Extras 1-3: 3 more clean updates for browser testing ──────────────────
print("\n[extra 1-3] 3 clean updates → pending_approval (for browser Approve/Reject/Quarantine)")
for extra_idx, (seed, round_num, client_id, key_id, priv_key, sample_count) in enumerate([
    (10, 3, "submit-client-1", "submit-key-1", priv1, 90),
    (20, 4, "submit-client-2", "submit-key-2", priv2, 120),
    (30, 5, "submit-client-1", "submit-key-1", priv1, 60),
], start=1):
    body_x, uid_x, raw_x = _build_body(
        client_id=client_id, key_id=key_id, private_key=priv_key,
        model_version="cnn-v1", round_number=round_num, sample_count=sample_count,
        state_dict=_cnn_v1_clean(seed),
    )
    sc_x, resp_x = _post(body_x)
    status_x = resp_x.get("status") if isinstance(resp_x, dict) else "?"
    print(f"  [{extra_idx}] HTTP {sc_x}  status={status_x}  update_id={uid_x}")
    if sc_x == 200:
        payloads_for_aggregation[uid_x] = {
            "client_id": client_id,
            "model_version": "cnn-v1",
            "round_number": round_num,
            "sample_count": sample_count,
            "payload_base64": body_x["payload_base64"],
        }

# ---------------------------------------------------------------------------
# 7.  Save payloads for aggregation test (task 3)
# ---------------------------------------------------------------------------
PAYLOADS_FILE = Path(__file__).parent / "demo_payloads.json"
PAYLOADS_FILE.write_text(json.dumps(payloads_for_aggregation, indent=2))
print(f"\n[saved] {len(payloads_for_aggregation)} clean payloads → {PAYLOADS_FILE.name}")

# ---------------------------------------------------------------------------
# 8.  Summary table
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  Summary")
print(SEP)
rows = [
    ("a", "clean → pending_approval",        sc_a, "200"),
    ("b", "huge weights → quarantined",       sc_b, "200"),
    ("c", "replay → blocked",                 sc_c, "409"),
    ("d", "tampered SHA-256 → rejected",      sc_d, "422"),
    ("e", "wrong schema → rejected",          sc_e, "422"),
    ("f", "unregistered key → unauthorized",  sc_f, "401"),
]
all_pass = True
for label, desc, actual, expected in rows:
    ok = str(actual) == expected
    icon = "PASS" if ok else "FAIL"
    if not ok:
        all_pass = False
    print(f"  [{label}] {icon}  HTTP {actual} (expected {expected})  — {desc}")

print()
print("  All cases PASSED." if all_pass else "  Some cases FAILED — see above.")
print(SEP)
print()
print("  Next steps:")
print("  1. Open http://localhost:5173 → Approvals page")
print("     Approve one, Reject one, Quarantine one of the pending updates")
print("  2. Check Audit Outbox for the 3 decisions")
print("  3. Run aggregation test: scripts/demo_aggregation.py")
print(SEP)
