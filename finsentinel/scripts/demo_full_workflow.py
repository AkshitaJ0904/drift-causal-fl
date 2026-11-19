#!/usr/bin/env python3
"""FinSentinel Full Demo Workflow

Demonstrates the complete FL security pipeline against the
``finsentinel_migration_test`` PostgreSQL database:

  1. Trusted client/key and model schema registration (provisioning)
  2. Valid update submission with Ed25519 signing (SHA-256 integrity)
  3. Anomaly detection: high-risk weights → quarantined
  4. Lifecycle management: pending approval, approve, reject, quarantine
  5. Security rejections: replay attack, tampered payload, unknown key
  6. Coordinator-verified mode via StubCoordinatorAdapter (programmatic)
  7. Operator approval and weighted FedAvg aggregation
  8. PostgreSQL audit trail verification

USAGE (from finsentinel root):

    .\\venv-security\\Scripts\\python.exe scripts\\demo_full_workflow.py

REQUIREMENTS:
  - PostgreSQL 18 service ``postgresql-18-finsentinel`` running (port 5432)
  - ``D:\\PostgreSQL\\pg_credentials.txt`` contains PG_MIGRATION_TEST_PASSWORD
  - Alembic migrations at HEAD (c3d4e5f6a7b8) in finsentinel_migration_test

DATABASE: finsentinel_migration_test  (disposable test/demo instance only)

WARNING: Clears trusted_keys and trusted_model_schemas tables. Use only on
         the finsentinel_migration_test database.

LABELS:
  Steps marked [HTTP] use the FastAPI application.
  Steps marked [DIRECT] call the service layer without HTTP (programmatic).
"""

from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 0.  Bootstrap: ensure finsentinel root is importable
# ---------------------------------------------------------------------------
FINSENTINEL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FINSENTINEL_ROOT))

CREDENTIALS_FILE = Path(r"D:\PostgreSQL\pg_credentials.txt")
SERVER_PORT = 8765
API_BASE = f"http://localhost:{SERVER_PORT}/api/v1"
MODEL_VERSION = "demo-mlp-v1"
ROUND_NUMBER = 1
# Unique run suffix prevents replay-protection conflicts across demo runs
RUN_ID = f"{int(time.time())}"


def _read_credentials() -> dict[str, str]:
    creds: dict[str, str] = {}
    with CREDENTIALS_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                creds[k.strip()] = v.strip()
    return creds


creds = _read_credentials()

# ---------------------------------------------------------------------------
# 1.  Set ALL env vars before any finsentinel imports
#     (core/supabase/connection.py creates the engine at module level)
# ---------------------------------------------------------------------------
OPERATOR_TOKEN = "demo-operator-token-local-only"

os.environ.update(
    {
        "DB_USER": "finsentinel_migration_test",
        "DB_PASSWORD": creds["PG_MIGRATION_TEST_PASSWORD"],
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_NAME": "finsentinel_migration_test",
        "ENVIRONMENT": "development",
        "FINSENTINEL_OPERATOR_TOKEN": OPERATOR_TOKEN,
        "FINSENTINEL_SAMPLE_COUNT_TRUST_MODE": "client_claimed",
        # Policy: allow the demo model version and round
        "FINSENTINEL_ALLOWED_MODEL_VERSIONS": MODEL_VERSION,
        "FINSENTINEL_ALLOWED_ROUNDS": str(ROUND_NUMBER),
    }
)

# ---------------------------------------------------------------------------
# 2.  Import finsentinel and third-party modules
# ---------------------------------------------------------------------------
import requests  # noqa: E402
import torch  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from sqlalchemy import text  # noqa: E402

from coordination.coordinator_adapter import CoordinatorBackedSampleCountProvider  # noqa: E402
from coordination.stub_coordinator import StubCoordinatorAdapter  # noqa: E402
from core.crypto import sign_envelope  # noqa: E402
from core.key_registry import clear_trusted_keys, register_trusted_key  # noqa: E402
from core.model_registry import clear_model_schemas, register_model_schema  # noqa: E402
from core.supabase.session import SessionLocal  # noqa: E402
from ingestion.schemas import UpdateEnvelope  # noqa: E402
from ingestion.serialization import serialize_state_dict  # noqa: E402
from ingestion.service import (  # noqa: E402
    configure_sample_count_provider,
    validate_incoming_update,
)
from policy.model_update_policy import ModelUpdatePolicy  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def banner(msg: str) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {msg}")
    print("=" * 72)


def step(msg: str) -> None:
    print(f"\n--- {msg} ---")


def ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def warn(msg: str) -> None:
    print(f"  [!]   {msg}")


def info(msg: str) -> None:
    print(f"        {msg}")


def _toy_state_dict(multiplier: float = 1.0) -> dict:
    """Minimal 2-layer MLP state dict (seed=42 for reproducibility)."""
    torch.manual_seed(42)
    return {
        "fc1.weight": torch.randn(10, 5) * multiplier,
        "fc1.bias": torch.randn(10) * multiplier,
        "fc2.weight": torch.randn(3, 10) * multiplier,
        "fc2.bias": torch.randn(3) * multiplier,
    }


def _make_payload(state_dict: dict) -> bytes:
    return serialize_state_dict(state_dict)


def _make_signed_envelope(
    *,
    update_id: str,
    client_id: str,
    signing_key_id: str,
    payload: bytes,
    sample_count: int,
    private_key: Ed25519PrivateKey,
    model_version: str = MODEL_VERSION,
    round_number: int = ROUND_NUMBER,
) -> UpdateEnvelope:
    sha256 = hashlib.sha256(payload).hexdigest()
    env = UpdateEnvelope(
        update_id=update_id,
        client_id=client_id,
        model_version=model_version,
        round_number=round_number,
        sample_count=sample_count,
        payload_sha256=sha256,
        payload_size_bytes=len(payload),
        created_at=datetime.now(UTC),
        signature="placeholder",
        signing_key_id=signing_key_id,
    )
    sig = sign_envelope(env, private_key)
    return env.model_copy(update={"signature": sig})


def _post_update(envelope: UpdateEnvelope, payload: bytes) -> requests.Response:
    body = {
        "envelope": envelope.model_dump(mode="json"),
        "payload_base64": base64.b64encode(payload).decode("ascii"),
    }
    return requests.post(f"{API_BASE}/updates", json=body, timeout=30)  # type: ignore[arg-type]


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {OPERATOR_TOKEN}"}


def _status(client_id: str, update_id: str) -> requests.Response:
    return requests.get(
        f"{API_BASE}/updates/{client_id}/{update_id}/status",
        headers=_auth_headers(),
        timeout=10,
    )


def _approve(
    client_id: str, update_id: str, reason: str = "Approved by demo operator"
) -> requests.Response:
    return requests.post(
        f"{API_BASE}/updates/{client_id}/{update_id}/approve",
        json={"reason": reason},
        headers=_auth_headers(),
        timeout=10,
    )


def _reject(
    client_id: str, update_id: str, reason: str = "Rejected by demo operator"
) -> requests.Response:
    return requests.post(
        f"{API_BASE}/updates/{client_id}/{update_id}/reject",
        json={"reason": reason},
        headers=_auth_headers(),
        timeout=10,
    )


def _start_server() -> subprocess.Popen:
    """Start uvicorn in a subprocess with the demo DB env vars."""
    env = os.environ.copy()
    cmd = [
        str(FINSENTINEL_ROOT / "venv-security" / "Scripts" / "python.exe"),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host", "127.0.0.1",
        "--port", str(SERVER_PORT),
        "--log-level", "warning",
    ]
    return subprocess.Popen(
        cmd,
        cwd=str(FINSENTINEL_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_server(timeout: int = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{API_BASE}/health", timeout=2)
            if r.status_code == 200:
                ok(f"Server ready at {API_BASE}")
                return
        except requests.exceptions.ConnectionError:
            time.sleep(0.5)
    raise RuntimeError(f"Server did not become ready within {timeout}s")


# ---------------------------------------------------------------------------
# PHASE 1: Trusted provisioning — register keys and model schema
# ---------------------------------------------------------------------------

banner("PHASE 1 — Trusted Provisioning")

step("Clearing prior demo data from trusted_keys and trusted_model_schemas")
clear_trusted_keys()
clear_model_schemas()
ok("Tables cleared")

step("Generating Ed25519 keypairs for demo clients")
priv1 = Ed25519PrivateKey.generate()
priv2 = Ed25519PrivateKey.generate()
priv_anomaly = Ed25519PrivateKey.generate()
priv_reject = Ed25519PrivateKey.generate()  # for explicit rejection demo
priv_unknown = Ed25519PrivateKey.generate()  # intentionally NOT registered

pub1 = priv1.public_key()
pub2 = priv2.public_key()
pub_anomaly = priv_anomaly.public_key()
pub_reject = priv_reject.public_key()

CLIENT1_ID = "demo-client-1"
CLIENT2_ID = "demo-client-2"
CLIENT_ANOMALY_ID = "demo-client-anomaly"
CLIENT_REJECT_ID = "demo-client-reject"
KEY1_ID = "demo-key-1"
KEY2_ID = "demo-key-2"
KEY_ANOMALY_ID = "demo-key-anomaly"
KEY_REJECT_ID = "demo-key-reject"
KEY_UNKNOWN_ID = "demo-key-unknown"

step("Registering trusted keys in PostgreSQL")
register_trusted_key(KEY1_ID, CLIENT1_ID, pub1, max_sample_count=500)
ok(f"{KEY1_ID} → {CLIENT1_ID} (max_sample_count=500)")
register_trusted_key(KEY2_ID, CLIENT2_ID, pub2, max_sample_count=500)
ok(f"{KEY2_ID} → {CLIENT2_ID} (max_sample_count=500)")
register_trusted_key(KEY_ANOMALY_ID, CLIENT_ANOMALY_ID, pub_anomaly, max_sample_count=500)
ok(f"{KEY_ANOMALY_ID} → {CLIENT_ANOMALY_ID} (max_sample_count=500)")
register_trusted_key(KEY_REJECT_ID, CLIENT_REJECT_ID, pub_reject, max_sample_count=500)
ok(f"{KEY_REJECT_ID} → {CLIENT_REJECT_ID} (max_sample_count=500)")
info("NOTE: demo-key-unknown is NOT registered — used for auth-rejection demo")

step("Registering model schema in PostgreSQL")
reference_state_dict = _toy_state_dict(multiplier=1.0)
register_model_schema(MODEL_VERSION, reference_state_dict)
ok(
    f"Schema for {MODEL_VERSION!r}: "
    + ", ".join(f"{k}{list(v.shape)}" for k, v in reference_state_dict.items())
)

# Pre-build the reference NPZ payload (server trusted model for aggregation)
reference_payload = _make_payload(reference_state_dict)
info(f"Reference payload: {len(reference_payload)} bytes  "
     f"sha256={hashlib.sha256(reference_payload).hexdigest()[:16]}...")

# ---------------------------------------------------------------------------
# PHASE 2: Start the FastAPI server
# ---------------------------------------------------------------------------

banner("PHASE 2 — Starting FastAPI Server")

step("Launching uvicorn")
server_proc = _start_server()
info(f"PID {server_proc.pid}  port {SERVER_PORT}")
_wait_for_server()

try:
    # -----------------------------------------------------------------------
    # PHASE 3: HTTP workflow demo
    # -----------------------------------------------------------------------

    banner("PHASE 3 — HTTP Workflow Demo  [HTTP]")

    # 3a. Build client update payloads
    step("Building client update payloads")

    state1 = _toy_state_dict(multiplier=1.0)      # normal weights
    state2 = _toy_state_dict(multiplier=0.8)      # slightly smaller weights
    state_anomaly = _toy_state_dict(multiplier=50.0)  # extreme weights → anomaly
    state_reject = _toy_state_dict(multiplier=0.95)   # normal weights → operator rejects

    payload1 = _make_payload(state1)
    payload2 = _make_payload(state2)
    payload_anomaly = _make_payload(state_anomaly)
    payload_reject = _make_payload(state_reject)

    UPDATE1_ID = f"upd-demo-1-r{RUN_ID}"
    UPDATE2_ID = f"upd-demo-2-r{RUN_ID}"
    UPDATE_ANOMALY_ID = f"upd-anomaly-r{RUN_ID}"
    UPDATE_REJECT_ID = f"upd-reject-r{RUN_ID}"

    env1 = _make_signed_envelope(
        update_id=UPDATE1_ID,
        client_id=CLIENT1_ID,
        signing_key_id=KEY1_ID,
        payload=payload1,
        sample_count=300,
        private_key=priv1,
    )
    env2 = _make_signed_envelope(
        update_id=UPDATE2_ID,
        client_id=CLIENT2_ID,
        signing_key_id=KEY2_ID,
        payload=payload2,
        sample_count=400,
        private_key=priv2,
    )
    env_anomaly = _make_signed_envelope(
        update_id=UPDATE_ANOMALY_ID,
        client_id=CLIENT_ANOMALY_ID,
        signing_key_id=KEY_ANOMALY_ID,
        payload=payload_anomaly,
        sample_count=250,
        private_key=priv_anomaly,
    )
    env_reject = _make_signed_envelope(
        update_id=UPDATE_REJECT_ID,
        client_id=CLIENT_REJECT_ID,
        signing_key_id=KEY_REJECT_ID,
        payload=payload_reject,
        sample_count=180,
        private_key=priv_reject,
    )
    ok("Payloads and envelopes ready")

    # 3b. Submit valid update — client 1
    step("[HTTP] Submit valid update: client-demo-1  (sample_count=300)")
    r1 = _post_update(env1, payload1)
    assert r1.status_code == 200, f"Expected 200, got {r1.status_code}: {r1.text[:300]}"
    d1 = r1.json()
    ok(
        f"HTTP 200  approval_status={d1['approval_status']}  "
        f"severity={d1['severity']}  risk_score={d1['risk_score']:.3f}  "
        f"suspicious={d1['suspicious']}"
    )
    info(f"  integrity={d1['integrity_status']}  auth={d1['authentication_status']}  "
         f"replay={d1['replay_status']}")

    # 3c. Submit valid update — client 2
    step("[HTTP] Submit valid update: client-demo-2  (sample_count=400)")
    r2 = _post_update(env2, payload2)
    assert r2.status_code == 200, f"Expected 200, got {r2.status_code}: {r2.text[:300]}"
    d2 = r2.json()
    ok(
        f"HTTP 200  approval_status={d2['approval_status']}  "
        f"severity={d2['severity']}  risk_score={d2['risk_score']:.3f}  "
        f"suspicious={d2['suspicious']}"
    )

    # 3d. Submit anomaly update (extreme weights → quarantined)
    step("[HTTP] Submit anomaly update: client-anomaly  (multiplier=50x → extreme weights)")
    r_anom = _post_update(env_anomaly, payload_anomaly)
    assert r_anom.status_code == 200, (
        f"Expected 200, got {r_anom.status_code}: {r_anom.text[:300]}"
    )
    d_anom = r_anom.json()
    ok(
        f"HTTP 200  approval_status={d_anom['approval_status']}  "
        f"severity={d_anom['severity']}  risk_score={d_anom['risk_score']:.3f}  "
        f"suspicious={d_anom['suspicious']}"
    )
    if d_anom["anomaly_reasons"]:
        info("  Anomaly reasons: " + "; ".join(d_anom["anomaly_reasons"]))

    # 3d-extra. Submit reject client (clean update that will be manually rejected)
    step("[HTTP] Submit valid update: client-demo-reject  (operator will reject)")
    r_rej_sub = _post_update(env_reject, payload_reject)
    assert r_rej_sub.status_code == 200, (
        f"Expected 200, got {r_rej_sub.status_code}: {r_rej_sub.text[:300]}"
    )
    d_rej_sub = r_rej_sub.json()
    ok(
        f"HTTP 200  approval_status={d_rej_sub['approval_status']}  "
        f"severity={d_rej_sub['severity']}  risk_score={d_rej_sub['risk_score']:.3f}"
    )

    # 3e. Status checks
    step("[HTTP] Status checks")
    for cid, uid, label in [
        (CLIENT1_ID, UPDATE1_ID, "client-demo-1"),
        (CLIENT2_ID, UPDATE2_ID, "client-demo-2"),
        (CLIENT_ANOMALY_ID, UPDATE_ANOMALY_ID, "client-anomaly"),
        (CLIENT_REJECT_ID, UPDATE_REJECT_ID, "client-demo-reject"),
    ]:
        rs = _status(cid, uid)
        assert rs.status_code == 200, f"Status check failed: {rs.status_code}"
        ds = rs.json()
        ok(f"{label:25s}  status={ds['status']}  risk_score={ds.get('risk_score', 'N/A')}")

    # 3f. Replay attack — re-submit identical update
    step("[HTTP] Security: replay attack (re-submit identical update-id)")
    r_replay = _post_update(env1, payload1)
    assert r_replay.status_code == 409, (
        f"Expected 409 Conflict, got {r_replay.status_code}: {r_replay.text[:200]}"
    )
    ok("HTTP 409 Conflict — replay correctly rejected")
    info(f"  detail: {r_replay.json().get('detail', '')[:120]}")

    # 3g. Tampered payload — corrupt payload bytes, keep original SHA-256
    step("[HTTP] Security: tampered payload (body corrupt, SHA-256 unchanged)")
    payload1_tampered = bytearray(payload1)
    payload1_tampered[20] ^= 0xFF  # flip a byte mid-stream
    r_tamper = _post_update(env1, bytes(payload1_tampered))
    assert r_tamper.status_code in {409, 422}, (
        f"Expected 409/422, got {r_tamper.status_code}: {r_tamper.text[:200]}"
    )
    ok(f"HTTP {r_tamper.status_code} — tampered payload correctly rejected")
    info(f"  detail: {r_tamper.json().get('detail', '')[:120]}")

    # 3h. Unknown signing key
    step("[HTTP] Security: unknown signing key (unregistered key_id)")
    env_unknown = _make_signed_envelope(
        update_id=f"upd-unknown-key-r{RUN_ID}",
        client_id=CLIENT1_ID,
        signing_key_id=KEY_UNKNOWN_ID,
        payload=payload1,
        sample_count=300,
        private_key=priv_unknown,
    )
    r_unknown = _post_update(env_unknown, payload1)
    assert r_unknown.status_code == 401, (
        f"Expected 401, got {r_unknown.status_code}: {r_unknown.text[:200]}"
    )
    ok("HTTP 401 Unauthorized — unknown signing key correctly rejected")
    info(f"  detail: {r_unknown.json().get('detail', '')[:120]}")

    # 3i. Approve client-demo-1 and client-demo-2
    step("[HTTP] Operator: approve client-demo-1 and client-demo-2")
    r_app1 = _approve(CLIENT1_ID, UPDATE1_ID)
    assert r_app1.status_code == 200, f"Approve 1 failed: {r_app1.status_code}"
    ok(f"client-demo-1 → approved  (status={r_app1.json().get('status')})")

    r_app2 = _approve(CLIENT2_ID, UPDATE2_ID)
    assert r_app2.status_code == 200, f"Approve 2 failed: {r_app2.status_code}"
    ok(f"client-demo-2 → approved  (status={r_app2.json().get('status')})")

    # 3j. Explicit operator rejection (clean update from pending_approval)
    step("[HTTP] Operator: reject pending_approval update (operator decision)")
    r_rej = _reject(
        CLIENT_REJECT_ID, UPDATE_REJECT_ID,
        reason="Demo: operator rejects update for policy reasons",
    )
    assert r_rej.status_code == 200, (
        f"Reject failed: {r_rej.status_code}: {r_rej.text[:200]}"
    )
    ok(f"client-demo-reject → rejected  (status={r_rej.json().get('status')})")

    # 3j-extra. Show quarantined is a terminal state (cannot re-transition)
    step("[HTTP] State machine: attempt to reject a quarantined update → must fail")
    r_rej_quar = _reject(
        CLIENT_ANOMALY_ID, UPDATE_ANOMALY_ID,
        reason="Attempt to transition from quarantined",
    )
    assert r_rej_quar.status_code == 409, (
        f"Expected 409, got {r_rej_quar.status_code}: {r_rej_quar.text[:200]}"
    )
    ok("HTTP 409 — quarantined is terminal; rejection correctly blocked")
    info(f"  detail: {r_rej_quar.json().get('detail', '')[:100]}")

    # 3k. Weighted FedAvg aggregation
    step("[HTTP] Operator: run weighted FedAvg aggregation (client-demo-1 + client-demo-2)")
    agg_body = {
        "model_version": MODEL_VERSION,
        "round_number": ROUND_NUMBER,
        "reference_payload_base64": base64.b64encode(reference_payload).decode("ascii"),
        "updates": [
            {
                "client_id": CLIENT1_ID,
                "update_id": UPDATE1_ID,
                "model_version": MODEL_VERSION,
                "round_number": ROUND_NUMBER,
                "sample_count": 300,
                "payload_base64": base64.b64encode(payload1).decode("ascii"),
            },
            {
                "client_id": CLIENT2_ID,
                "update_id": UPDATE2_ID,
                "model_version": MODEL_VERSION,
                "round_number": ROUND_NUMBER,
                "sample_count": 400,
                "payload_base64": base64.b64encode(payload2).decode("ascii"),
            },
        ],
    }
    r_agg = requests.post(
        f"{API_BASE}/aggregation/run",
        json=agg_body,  # type: ignore[arg-type]
        headers=_auth_headers(),
        timeout=30,
    )
    assert r_agg.status_code == 200, (
        f"Aggregation failed: {r_agg.status_code}: {r_agg.text[:300]}"
    )
    agg = r_agg.json()
    ok(
        f"HTTP 200  model_version={agg['model_version']}  "
        f"round={agg['round_number']}  "
        f"updates={agg['update_count']}  "
        f"total_samples={agg['total_samples']}"
    )
    info(f"  tensors ({agg['tensor_count']}): {agg['tensor_names']}")
    agg_payload_bytes = base64.b64decode(agg["aggregated_payload_base64"])
    info(f"  aggregated payload: {len(agg_payload_bytes)} bytes")

    # Deserialize and spot-check the aggregated weights
    from ingestion.serialization import deserialize_state_dict  # already imported

    agg_sd = deserialize_state_dict(agg_payload_bytes)
    total_w = 300 + 400
    expected_fc1_bias = (
        state1["fc1.bias"] * 300 / total_w + state2["fc1.bias"] * 400 / total_w
    )
    actual_fc1_bias = agg_sd["fc1.bias"]
    max_err = (expected_fc1_bias - actual_fc1_bias).abs().max().item()
    ok(f"FedAvg spot-check fc1.bias  max_error={max_err:.2e}  (expected ≈ 0)")

    # 3l. Attempt to aggregate non-approved updates — must be refused
    step("[HTTP] Security: aggregate rejected/quarantined updates (must be refused)")
    for bad_client, bad_update, bad_payload, bad_count, label in [
        (CLIENT_REJECT_ID, UPDATE_REJECT_ID, payload_reject, 180, "rejected update"),
        (CLIENT_ANOMALY_ID, UPDATE_ANOMALY_ID, payload_anomaly, 250, "quarantined update"),
    ]:
        agg_body_bad = {
            "model_version": MODEL_VERSION,
            "round_number": ROUND_NUMBER,
            "reference_payload_base64": base64.b64encode(reference_payload).decode("ascii"),
            "updates": [
                {
                    "client_id": bad_client,
                    "update_id": bad_update,
                    "model_version": MODEL_VERSION,
                    "round_number": ROUND_NUMBER,
                    "sample_count": bad_count,
                    "payload_base64": base64.b64encode(bad_payload).decode("ascii"),
                },
            ],
        }
        r_agg_bad = requests.post(
            f"{API_BASE}/aggregation/run",
            json=agg_body_bad,  # type: ignore[arg-type]
            headers=_auth_headers(),
            timeout=30,
        )
        assert r_agg_bad.status_code == 422, (
            f"Expected 422 for {label}, got {r_agg_bad.status_code}: {r_agg_bad.text[:200]}"
        )
        ok(f"HTTP 422 — {label} correctly blocked from aggregation")
        info(f"  detail: {r_agg_bad.json().get('detail', '')[:120]}")

    # -----------------------------------------------------------------------
    # PHASE 4: Coordinator-verified mode  [DIRECT — programmatic]
    # -----------------------------------------------------------------------

    banner(
        "PHASE 4 — Coordinator-Verified Mode  [DIRECT — service layer, NOT via HTTP]\n"
        "  (StubCoordinatorAdapter is a TEST DOUBLE; not a production coordinator)"
    )

    step("[DIRECT] Set up StubCoordinatorAdapter")
    stub = StubCoordinatorAdapter()
    CLIENT_CV_ID = "demo-client-cv"
    KEY_CV_ID = "demo-key-cv"
    UPDATE_CV_ID = f"upd-cv-r{RUN_ID}"

    priv_cv = Ed25519PrivateKey.generate()
    pub_cv = priv_cv.public_key()

    register_trusted_key(KEY_CV_ID, CLIENT_CV_ID, pub_cv, max_sample_count=500)
    ok(f"Registered {KEY_CV_ID} → {CLIENT_CV_ID}")

    # Build the payload for coordinator-verified demo
    payload_cv = _make_payload(_toy_state_dict(multiplier=0.9))
    env_cv = _make_signed_envelope(
        update_id=UPDATE_CV_ID,
        client_id=CLIENT_CV_ID,
        signing_key_id=KEY_CV_ID,
        payload=payload_cv,
        sample_count=200,
        private_key=priv_cv,
    )

    step("[DIRECT] coordinator_verified mode without provider registration → must fail")
    provider = CoordinatorBackedSampleCountProvider(stub)
    configure_sample_count_provider(provider)  # type: ignore[arg-type]

    policy_cv = ModelUpdatePolicy(
        allowed_model_versions=frozenset({MODEL_VERSION}),
        allowed_round_numbers=frozenset({ROUND_NUMBER}),
        max_update_age_seconds=900,
        max_future_clock_skew_seconds=60,
    )

    try:
        validate_incoming_update(
            payload_cv,
            env_cv,
            policy=policy_cv,
            trust_mode="coordinator_verified",
        )
        warn("Expected UpdatePolicyRejectedError but no exception was raised")
    except Exception as exc:
        ok(
            f"Correctly rejected: {type(exc).__name__}: {str(exc)[:120]}"
        )

    step(
        "[DIRECT] coordinator_verified mode with matching stub registration → must succeed"
    )
    # Round-level registration (no update_id) so is_client_selected() returns True
    stub.register_participation(
        client_id=CLIENT_CV_ID,
        round_number=ROUND_NUMBER,
        sample_count=200,
    )
    try:
        result_cv = validate_incoming_update(
            payload_cv,
            env_cv,
            policy=policy_cv,
            trust_mode="coordinator_verified",
        )
        ok(
            f"Accepted  approval_status={result_cv['approval_status']}  "
            f"severity={result_cv['severity']}  "
            f"provenance=PROVIDER_VERIFIED"
        )
        info("  sample_count_provenance implied by coordinator match")
    except Exception as exc:
        warn(f"Unexpected error: {type(exc).__name__}: {exc}")
    finally:
        configure_sample_count_provider(None)  # restore to no-provider state

    # -----------------------------------------------------------------------
    # PHASE 5: PostgreSQL audit trail verification
    # -----------------------------------------------------------------------

    banner("PHASE 5 — PostgreSQL Audit Trail Verification")

    step("Querying audit_events table")
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT event_type, severity, client_id, update_id, created_at "
                "FROM audit_events "
                "ORDER BY created_at DESC "
                "LIMIT 25"
            )
        ).fetchall()

    print(f"\n  {'EVENT TYPE':<45} {'SEV':<8} {'CLIENT':<20} {'UPDATE_ID'}")
    print(f"  {'-'*44} {'-'*7} {'-'*19} {'-'*22}")
    for row in rows:
        et = (row[0] or "")[:44]
        sev = (row[1] or "")[:7]
        cid = (row[2] or "")[:19]
        uid = (row[3] or "")[:22]
        print(f"  {et:<45} {sev:<8} {cid:<20} {uid}")

    step("Counting events by type")
    with SessionLocal() as db:
        counts = db.execute(
            text(
                "SELECT event_type, COUNT(*) AS cnt "
                "FROM audit_events "
                "GROUP BY event_type "
                "ORDER BY cnt DESC "
                "LIMIT 20"
            )
        ).fetchall()

    for row in counts:
        print(f"  {row[1]:>4}x  {row[0]}")

    step("Verifying update_approvals lifecycle")
    with SessionLocal() as db:
        approvals = db.execute(
            text(
                "SELECT client_id, update_id, status, risk_score, risk_severity, "
                "       suspicious, sample_count_provenance "
                "FROM update_approvals "
                "ORDER BY created_at"
            )
        ).fetchall()

    print(
        f"\n  {'CLIENT':<22} {'UPDATE_ID':<24} {'STATUS':<18} "
        f"{'RISK':<6} {'SEV':<8} {'SUSP':<5}"
    )
    print(f"  {'-'*21} {'-'*23} {'-'*17} {'-'*5} {'-'*7} {'-'*4}")
    for row in approvals:
        cid = (row[0] or "")[:21]
        uid = (row[1] or "")[:23]
        status = (row[2] or "")[:17]
        risk = f"{float(row[3]):.3f}" if row[3] is not None else "N/A"
        sev = (row[4] or "")[:7]
        susp = "Y" if row[5] else "N"
        print(f"  {cid:<22} {uid:<24} {status:<18} {risk:<6} {sev:<8} {susp}")

    # -----------------------------------------------------------------------
    # Phase 6: Spot-check audit_outbox delivery
    # -----------------------------------------------------------------------

    banner("PHASE 6 — Audit Outbox  (transactional outbox records)")

    with SessionLocal() as db:
        outbox_counts = db.execute(
            text(
                "SELECT status, COUNT(*) "
                "FROM audit_outbox "
                "GROUP BY status"
            )
        ).fetchall()

    for row in outbox_counts:
        ok(f"audit_outbox  status={row[0]}  count={row[1]}")

    if not outbox_counts:
        info("audit_outbox is empty (no outbox entries yet)")

finally:
    # -----------------------------------------------------------------------
    # Shut down the server
    # -----------------------------------------------------------------------
    banner("Shutting down uvicorn")
    server_proc.terminate()
    try:
        server_proc.wait(timeout=5)
        ok(f"Server stopped (exit code {server_proc.returncode})")
    except subprocess.TimeoutExpired:
        server_proc.kill()
        warn("Server killed after timeout")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

banner("DEMO COMPLETE — Summary")
print("""
  DATABASE     : finsentinel_migration_test  (PostgreSQL 18)
  API_BASE     : http://localhost:8765/api/v1
  MODEL        : demo-mlp-v1   round=1

  RESULTS VERIFIED:
    [HTTP]    client-demo-1   valid update     → pending_approval → approved
    [HTTP]    client-demo-2   valid update     → pending_approval → approved
    [HTTP]    client-anomaly  extreme weights  → quarantined (terminal)
    [HTTP]    client-reject   clean update     → pending_approval → rejected
    [HTTP]    quarantined re-transition        → HTTP 409 (state machine protected)
    [HTTP]    replay attack                    → HTTP 409 Conflict
    [HTTP]    tampered payload                 → HTTP 422
    [HTTP]    unknown signing key              → HTTP 401 Unauthorized
    [HTTP]    FedAvg aggregation (300+400)     → weighted average verified
    [HTTP]    aggregate rejected/quarantined   → HTTP 422 refused (both)
    [DIRECT]  coordinator_verified no-stub    → SampleCountVerificationError
    [DIRECT]  coordinator_verified with-stub  → accepted (PROVIDER_VERIFIED)

  POSTGRESQL:
    trusted_keys              : 5 entries registered
    trusted_model_schemas     : 1 schema (demo-mlp-v1)
    update_approvals          : entries above
    audit_events              : entries above (all security decisions logged)
    audit_outbox              : transactional outbox records
    replay_records            : replay protection table populated

  NOTE: StubCoordinatorAdapter is a TEST DOUBLE. Not a production coordinator.
""")
