"""FinSentinel -> Wazuh end-to-end demo (real pipeline, no shortcuts).

Every event is produced by FinSentinel itself and travels the production path:

    POST /api/v1/updates  ->  ingestion security checks  ->  audit outbox
    ->  delivery worker (Bearer webhook)  ->  scripts/siem_forwarder.py
    ->  logs/finsentinel-siem.jsonl  ->  Wazuh manager <localfile json>  ->  alert

This script never writes the JSONL file. It only submits requests through the
public ingestion API (keys are provisioned with core.key_registry, the
supported trusted-provisioning function) and then verifies that each expected
event_type arrived in the JSONL via the forwarder.

Prerequisites (from finsentinel/):
  1. scripts/siem_forwarder.py running (FINSENTINEL_AUDIT_WEBHOOK_TOKEN set)
  2. backend running with FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED=1,
     FINSENTINEL_AUDIT_WEBHOOK_URL=http://127.0.0.1:9999/ingest and the same token
  3. .\\venv-security\\Scripts\\python.exe scripts\\demo_wazuh_events.py

Private keys are generated per run, kept in memory only, never printed.
It leaves 3 updates PENDING for the operator to approve / reject / quarantine
in the dashboard. Nothing is auto-approved.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import time
import types
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
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

_engine = create_engine(
    f"sqlite:///{REPO_ROOT / 'finsentinel_dev.db'}", connect_args={"check_same_thread": False}
)
_fake_conn = types.ModuleType("core.supabase.connection")
_fake_conn.engine = _engine  # type: ignore[attr-defined]
sys.modules["core.supabase.connection"] = _fake_conn

import core.supabase.session as _session_module  # noqa: E402

_session_module.SessionLocal.configure(bind=_engine)

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from core.crypto import sign_envelope  # noqa: E402
from core.key_registry import register_trusted_key  # noqa: E402
from ingestion.schemas import UpdateEnvelope  # noqa: E402

API_URL = "http://localhost:8000/api/v1/updates"
_DEFAULT_LOG = str(REPO_ROOT / "logs" / "finsentinel-siem.jsonl")
SIEM_LOG = Path(os.environ.get("FINSENTINEL_SIEM_LOG", _DEFAULT_LOG))
RUN = uuid.uuid4().hex[:6]


# --------------------------------------------------------------------------- payloads
def _make_payload(state: dict[str, np.ndarray]) -> bytes:
    """Serialize tensors in FinSentinel's NPZ + manifest format."""
    arrays: dict[str, np.ndarray] = {}
    tensors = []
    for i, (name, arr) in enumerate(state.items()):
        key = f"tensor_{i:06d}"
        arrays[key] = arr
        tensors.append({
            "archive_key": key, "dtype": arr.dtype.str,
            "name": name, "shape": list(arr.shape),
        })
    manifest = {"format_version": 1, "tensor_count": len(tensors), "tensors": tensors}
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    arrays["__manifest__"] = np.frombuffer(raw, dtype=np.uint8)
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)  # type: ignore[arg-type]
    return buf.getvalue()


def _cnn(seed: int, scale: float = 0.05, fc1_in: int = 400) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    return {
        "conv1.weight": rng.standard_normal((8, 1, 3, 3)).astype(np.float32) * scale,
        "conv1.bias": np.zeros(8, dtype=np.float32),
        "conv2.weight": rng.standard_normal((16, 8, 3, 3)).astype(np.float32) * scale,
        "conv2.bias": np.zeros(16, dtype=np.float32),
        "fc1.weight": rng.standard_normal((128, fc1_in)).astype(np.float32) * scale,
        "fc1.bias": np.zeros(128, dtype=np.float32),
        "fc2.weight": rng.standard_normal((10, 128)).astype(np.float32) * scale,
        "fc2.bias": np.zeros(10, dtype=np.float32),
    }


def _body(
    *,
    client_id: str,
    key_id: str,
    signer: Ed25519PrivateKey,
    round_number: int,
    state: dict[str, np.ndarray],
    tamper_sha: bool = False,
) -> dict[str, Any]:
    payload = _make_payload(state)
    sha = hashlib.sha256(payload).hexdigest()
    if tamper_sha:
        sha = sha[:-1] + ("a" if sha[-1] != "a" else "b")
    base = {
        "update_id": str(uuid.uuid4()),
        "client_id": client_id,
        "model_version": "cnn-v1",
        "round_number": round_number,
        "sample_count": 100,
        "payload_sha256": sha,
        "payload_size_bytes": len(payload),
        "created_at": datetime.now(UTC).isoformat(),
        "signature": "PENDING",
        "signing_key_id": key_id,
    }
    sig = sign_envelope(UpdateEnvelope(**base), signer)  # type: ignore[arg-type]
    env = UpdateEnvelope(**{**base, "signature": sig})  # type: ignore[arg-type]
    return {
        "envelope": env.model_dump(mode="json"),
        "payload_base64": base64.b64encode(payload).decode(),
    }


def _post(body: dict[str, Any]) -> tuple[int, str]:
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read() or b"{}")
            return int(resp.status), str(data.get("status", ""))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", "")
        except (json.JSONDecodeError, ValueError):
            detail = ""
        return int(exc.code), str(detail)[:60]


def _jsonl_count() -> int:
    if not SIEM_LOG.exists():
        return 0
    with SIEM_LOG.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


def _new_events(start: int) -> list[dict[str, Any]]:
    if not SIEM_LOG.exists():
        return []
    with SIEM_LOG.open(encoding="utf-8") as f:
        lines = f.read().splitlines()[start:]
    return [json.loads(x) for x in lines if x.strip()]


def main() -> int:
    start = _jsonl_count()
    c1, c2 = f"bank-mumbai-{RUN}", f"bank-delhi-{RUN}"
    k1, k2 = f"bank-mumbai-key-{RUN}", f"bank-delhi-key-{RUN}"
    p1, p2 = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    attacker = Ed25519PrivateKey.generate()  # never registered

    print(f"[setup] run={RUN}  provisioning 2 trusted keys via core.key_registry")
    register_trusted_key(k1, c1, p1.public_key(), max_sample_count=1000)
    register_trusted_key(k2, c2, p2.public_key(), max_sample_count=1000)

    valid = _body(client_id=c1, key_id=k1, signer=p1, round_number=1, state=_cnn(1))
    scenarios: list[tuple[str, dict[str, Any], list[str]]] = [
        (
            "S1 valid signed update", valid,
            ["security.update_authenticated", "security.anomaly_clean",
             "security.update_pending_approval"],
        ),
        (
            "S2 invalid signature",
            _body(client_id=c1, key_id=k1, signer=attacker, round_number=1, state=_cnn(2)),
            ["security.signature_verification_failed"],
        ),
        (
            "S3 SHA-256 tamper",
            _body(client_id=c1, key_id=k1, signer=p1, round_number=1,
                  state=_cnn(3), tamper_sha=True),
            ["security.payload_integrity_failed"],
        ),
        ("S4 replay of S1", valid, ["security.replay_detected"]),
        (
            "S5 schema violation",
            _body(client_id=c1, key_id=k1, signer=p1, round_number=1,
                  state=_cnn(5, fc1_in=100)),
            ["security.model_schema_rejected"],
        ),
        (
            "S6 anomalous (huge weights)",
            _body(client_id=c2, key_id=k2, signer=p2, round_number=1,
                  state=_cnn(6, scale=50.0)),
            ["security.anomaly_detected", "security.update_quarantined"],
        ),
        (
            "S7 unregistered key",
            _body(client_id=c1, key_id=f"ghost-key-{RUN}", signer=attacker,
                  round_number=1, state=_cnn(7)),
            ["security.unknown_signing_key"],
        ),
        (
            "S8 key/client mismatch",
            _body(client_id=c2, key_id=k1, signer=p1, round_number=1, state=_cnn(8)),
            ["security.client_key_mismatch"],
        ),
        (
            "S9 pending for operator #1",
            _body(client_id=c1, key_id=k1, signer=p1, round_number=2, state=_cnn(9)),
            ["security.update_pending_approval"],
        ),
        (
            "S10 pending for operator #2",
            _body(client_id=c2, key_id=k2, signer=p2, round_number=2, state=_cnn(10)),
            ["security.update_pending_approval"],
        ),
    ]
    for i in range(5):
        scenarios.append((
            f"S11 brute-force bad signature {i + 1}/5",
            _body(client_id=c1, key_id=k1, signer=attacker, round_number=3, state=_cnn(20 + i)),
            ["security.signature_verification_failed"],
        ))

    print(f"\n{'Scenario':38} {'HTTP':>4}  Result")
    print("-" * 78)
    for name, body, _ in scenarios:
        code, info = _post(body)
        print(f"{name:38} {code:>4}  {info}")

    print("\n[verify] waiting for outbox -> webhook -> forwarder -> JSONL ...")
    expected = {"key.registered"} | {e for _, _, evs in scenarios for e in evs}
    seen: dict[str, int] = {}
    for _ in range(30):
        time.sleep(2)
        seen = {}
        for ev in _new_events(start):
            if RUN in str(ev.get("client_id", "")) or RUN in str(ev.get("description", "")):
                seen[ev["event_type"]] = seen.get(ev["event_type"], 0) + 1
        if expected <= set(seen):
            break

    print(f"\n{'event_type (from this run)':44} {'in JSONL':>8}")
    print("-" * 56)
    ok = True
    for etype in sorted(expected):
        n = seen.get(etype, 0)
        ok &= n > 0
        print(f"{etype:44} {n:>8}  {'PASS' if n else 'MISSING'}")
    print("\nResult:", "ALL EVENTS DELIVERED VIA PIPELINE" if ok else "SOME EVENTS MISSING")
    print("Next: approve / reject / quarantine the 3 pending updates in the dashboard,")
    print("then check Wazuh: Threat Hunting -> filter rule.groups: finsentinel")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
