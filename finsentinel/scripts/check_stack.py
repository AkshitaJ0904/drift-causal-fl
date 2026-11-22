"""Stack health check — prints status codes/booleans only, never secrets."""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

TOKEN_FILE = Path.home() / ".finsentinel" / "dev_token.txt"
if not TOKEN_FILE.exists():
    raise SystemExit("Token file not found")
_token = TOKEN_FILE.read_text().strip()

BASE = "http://127.0.0.1:8000/api/v1"


def _get(path: str, auth: bool = True) -> int:
    url = f"http://127.0.0.1:8000{path}"
    headers = {"Authorization": f"Bearer {_token}"} if auth else {}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def _json(path: str) -> dict:
    url = f"http://127.0.0.1:8000{path}"
    headers = {"Authorization": f"Bearer {_token}"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def _forwarder() -> int:
    try:
        req = urllib.request.Request("http://127.0.0.1:9999/health")
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def _docker_health() -> dict[str, str]:
    containers = [
        "wazuh-manager", "wazuh-indexer", "wazuh-dashboard", "finsentinel-postgres"
    ]
    out: dict[str, str] = {}
    for c in containers:
        for cmd in (["wsl", "docker"], ["docker"]):
            try:
                r = subprocess.run(
                    cmd + ["inspect", "--format", "{{.State.Health.Status}}", c],
                    capture_output=True, text=True, timeout=8
                )
                val = r.stdout.strip()
                if val:
                    out[c] = val
                    break
            except Exception:
                pass
        else:
            out[c] = "unreachable"
    return out


print("=== FinSentinel stack check ===")
print(f"/api/v1/health               : {_get('/api/v1/health', auth=False)}")
print(f"/api/v1/security-events      : {_get('/api/v1/security-events')}")
print(f"/api/v1/security-events/catalog: {_get('/api/v1/security-events/catalog')}")
print(f"/api/v1/vapt-report          : {_get('/api/v1/vapt-report')}")

dash = _json("/api/v1/operator/dashboard")
worker = dash.get("worker", {})
outbox = dash.get("outbox", {})
print(f"worker.enabled               : {worker.get('enabled')}")
print(f"worker.webhook_configured    : {worker.get('webhook_configured')}")
# 25 dead-letters from run 37dfac (forwarder was down, 10 attempts exhausted); unrelated to VAPT
print(f"outbox.dead_letter_count     : {outbox.get('dead_letter_count')}")

print(f"forwarder :9999 /health      : {_forwarder()}")
print("--- docker container health ---")
for name, status in _docker_health().items():
    print(f"  {name:<30}: {status}")
