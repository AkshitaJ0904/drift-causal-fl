"""FinSentinel aggregation API test.

Tests:
  1. Approved update (extra-1, round 3) → 200 aggregated model
  2. Rejected update (extra-2, round 4) → 422 "not approved"
  3. Quarantined update (extra-3, round 5) → 422 "not approved"
  4. Pending update (case-a, round 1) → 422 "not approved"
  5. Zero updates (omitted — Pydantic min_length=1) → 422 validation error
  6. Round mismatch: approved payload submitted with wrong round number → 422

Pre-requisite: open http://localhost:5173 → Approvals page and:
  • Approve   extra-1 (5a0c51b9…)
  • Reject    extra-2 (935a8dcd…)
  • Quarantine extra-3 (3d6e4b39…)
  • Leave     case-a  (aa138d10…) pending

Usage (from finsentinel/ directory, backend running on :8000):
    .\\venv-security\\Scripts\\python.exe scripts\\demo_aggregation.py

Reads operator token from dev_token.txt (never prints it).
IDs are sourced dynamically from scripts/demo_payloads.json — run
demo_submit_updates.py first whenever the demo DB is reset.
"""
from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).parent.parent
PAYLOADS_FILE = Path(__file__).parent / "demo_payloads.json"
API_BASE = "http://localhost:8000/api/v1"
SEP = "=" * 72

# ---------------------------------------------------------------------------
# Token — read silently, never printed
# ---------------------------------------------------------------------------
_token_file = Path.home() / ".finsentinel" / "dev_token.txt"
if not _token_file.exists():
    raise SystemExit(
        "~/.finsentinel/dev_token.txt not found — start the backend (run_dev.py) first."
    )
_TOKEN = _token_file.read_text().strip()
if len(_TOKEN) < 32:
    raise SystemExit("~/.finsentinel/dev_token.txt contains a token that is too short.")

_AUTH_HEADER = {"Authorization": f"Bearer {_TOKEN}",
                "Content-Type": "application/json"}

# ---------------------------------------------------------------------------
# Load saved payloads
# ---------------------------------------------------------------------------
if not PAYLOADS_FILE.exists():
    raise SystemExit("demo_payloads.json not found — run demo_submit_updates.py first.")

payloads: dict = json.loads(PAYLOADS_FILE.read_text())

# IDs are read from demo_payloads.json (populated by demo_submit_updates.py).
# Assignment: extra-1 → approve, extra-2 → reject, extra-3 → quarantine, case-a → leave pending.
_ids = list(payloads.keys())
if len(_ids) < 4:
    raise SystemExit(
        f"demo_payloads.json has only {len(_ids)} entries — run demo_submit_updates.py first."
    )
APPROVED_ID    = _ids[1]  # extra-1 (round 3) — operator must approve in UI
REJECTED_ID    = _ids[2]  # extra-2 (round 4) — operator must reject in UI
QUARANTINED_ID = _ids[3]  # extra-3 (round 5) — operator must quarantine in UI
PENDING_ID     = _ids[0]  # case-a  (round 1) — leave pending in UI

for uid in [APPROVED_ID, REJECTED_ID, QUARANTINED_ID, PENDING_ID]:
    if uid not in payloads:
        raise SystemExit(
            f"Update {uid} not in demo_payloads.json — run demo_submit_updates.py first."
        )

# ---------------------------------------------------------------------------
# Reference model: minimal cnn-v1 NPZ (all-zeros, same schema)
# ---------------------------------------------------------------------------
def _make_reference_npz() -> bytes:
    """Build a clean cnn-v1 reference model (all zeros)."""
    state: dict[str, np.ndarray] = {
        "conv1.weight": np.zeros((8, 1, 3, 3), dtype=np.float32),
        "conv1.bias":   np.zeros(8, dtype=np.float32),
        "conv2.weight": np.zeros((16, 8, 3, 3), dtype=np.float32),
        "conv2.bias":   np.zeros(16, dtype=np.float32),
        "fc1.weight":   np.zeros((128, 400), dtype=np.float32),
        "fc1.bias":     np.zeros(128, dtype=np.float32),
        "fc2.weight":   np.zeros((10, 128), dtype=np.float32),
        "fc2.bias":     np.zeros(10, dtype=np.float32),
    }
    arrays: dict[str, np.ndarray] = {}
    manifest_tensors = []
    for i, (name, arr) in enumerate(state.items()):
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

_REF_B64 = base64.b64encode(_make_reference_npz()).decode()


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def _post(path: str, body: dict) -> tuple[int, dict | str]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API_BASE}{path}", data=data, headers=_AUTH_HEADER
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


def _update_body(uid: str, round_override: int | None = None) -> dict:
    p = payloads[uid]
    return {
        "client_id": p["client_id"],
        "update_id": uid,
        "model_version": p["model_version"],
        "round_number": round_override if round_override is not None else p["round_number"],
        "sample_count": p["sample_count"],
        "payload_base64": p["payload_base64"],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
print(SEP)
print("  FinSentinel Aggregation API Test")
print(SEP)

results: list[tuple[str, str, int, str, bool]] = []  # (label, desc, actual, expected, pass)


def run_test(label: str, desc: str, path: str, body: dict, expected_code: int) -> dict | str:
    sc, resp = _post(path, body)
    ok = sc == expected_code
    icon = "PASS" if ok else "FAIL"
    detail = resp.get("detail", "") if isinstance(resp, dict) else str(resp)[:120]
    results.append((label, desc, sc, str(expected_code), ok))
    print(f"\n[{label}] {icon}  HTTP {sc} (expected {expected_code})")
    print(f"  desc  : {desc}")
    if not ok or label == "1":
        # print full detail for the success case + failures
        print(f"  detail: {detail[:200]}")
    return resp


# Test 1: Approved update (round 1) → 200
p_approved = payloads[APPROVED_ID]
body1 = {
    "model_version": "cnn-v1",
    "round_number": p_approved["round_number"],
    "updates": [_update_body(APPROVED_ID)],
    "reference_payload_base64": _REF_B64,
}
label1 = (
    f"Approved update ({APPROVED_ID[:8]} round {p_approved['round_number']})"
    " → aggregated model"
)
resp1 = run_test("1", label1, "/aggregation/run", body1, 200)
if isinstance(resp1, dict) and resp1.get("aggregated_payload_base64"):
    print(f"  tensor_count : {resp1.get('tensor_count')}")
    print(f"  total_samples: {resp1.get('total_samples')}")
    print(f"  tensor_names : {resp1.get('tensor_names')}")
    print(f"  output_bytes : {len(resp1['aggregated_payload_base64'])} b64 chars")


# Test 2: Rejected update → 422
p_rej = payloads[REJECTED_ID]
body2 = {
    "model_version": "cnn-v1",
    "round_number": p_rej["round_number"],
    "updates": [_update_body(REJECTED_ID)],
    "reference_payload_base64": _REF_B64,
}
resp2 = run_test(
    "2", f"Rejected update ({REJECTED_ID[:8]}) → not approved → 422",
    "/aggregation/run", body2, 422
)
print(f"  detail: {resp2.get('detail', resp2) if isinstance(resp2, dict) else resp2}")


# Test 3: Quarantined update → 422
p_qua = payloads[QUARANTINED_ID]
body3 = {
    "model_version": "cnn-v1",
    "round_number": p_qua["round_number"],
    "updates": [_update_body(QUARANTINED_ID)],
    "reference_payload_base64": _REF_B64,
}
resp3 = run_test(
    "3", f"Quarantined update ({QUARANTINED_ID[:8]}) → not approved → 422",
    "/aggregation/run", body3, 422
)
print(f"  detail: {resp3.get('detail', resp3) if isinstance(resp3, dict) else resp3}")


# Test 4: Pending update → 422
p_pend = payloads[PENDING_ID]
body4 = {
    "model_version": "cnn-v1",
    "round_number": p_pend["round_number"],
    "updates": [_update_body(PENDING_ID)],
    "reference_payload_base64": _REF_B64,
}
resp4 = run_test(
    "4", f"Pending update ({PENDING_ID[:8]}) → not approved → 422",
    "/aggregation/run", body4, 422
)
print(f"  detail: {resp4.get('detail', resp4) if isinstance(resp4, dict) else resp4}")


# Test 5: Zero updates — Pydantic rejects updates list with min_length=1 → 422
body5 = {
    "model_version": "cnn-v1",
    "round_number": 1,
    "updates": [],
    "reference_payload_base64": _REF_B64,
}
resp5 = run_test(
    "5", "Empty updates list (len=0) → Pydantic 422",
    "/aggregation/run", body5, 422
)
print(f"  detail: {str(resp5)[:120]}")


# Test 6: Round mismatch — approved payload sent with wrong round_number → 422
body6 = {
    "model_version": "cnn-v1",
    "round_number": 99,  # actual round is 1
    "updates": [{**_update_body(APPROVED_ID), "round_number": 99}],
    "reference_payload_base64": _REF_B64,
}
resp6 = run_test(
    "6", f"Round mismatch (round=99 vs approved round={p_approved['round_number']}) → 422",
    "/aggregation/run", body6, 422
)
print(f"  detail: {resp6.get('detail', resp6) if isinstance(resp6, dict) else resp6}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  Summary")
print(SEP)
all_pass = all(ok for *_, ok in results)
for label, desc, actual, expected, ok in results:
    icon = "PASS" if ok else "FAIL"
    print(f"  [{label}] {icon}  HTTP {actual} (expected {expected})  — {desc}")
print()
print("  All aggregation tests PASSED." if all_pass else "  SOME TESTS FAILED — see above.")
print(SEP)
