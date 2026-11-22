"""FinSentinel SIEM forwarder — local webhook receiver.

Receives POST requests from the FinSentinel outbox delivery worker
(FINSENTINEL_AUDIT_WEBHOOK_URL = http://127.0.0.1:9999/ingest),
verifies the Bearer token, deduplicates on idempotency_key, and
appends one JSONL record to logs/finsentinel-siem.jsonl for each
new event.  Wazuh agent (or manager localfile) tails that file.

Authentication
--------------
Reads FINSENTINEL_AUDIT_WEBHOOK_TOKEN from the environment.
Comparison is constant-time to prevent timing attacks.
Rejects requests with missing or wrong token with HTTP 401.

Deduplication
-------------
In-memory set of seen idempotency_keys.  Process restart clears
the set, but that is safe because an already-written JSONL record
is idempotent — Wazuh will process it only once from the file.

Usage (from finsentinel/ directory)
------------------------------------
    # Terminal 1 — start the forwarder
    .\\venv-security\\Scripts\\python.exe scripts\\siem_forwarder.py

    # Terminal 2 — start the backend with delivery worker enabled
    set FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED=1
    set FINSENTINEL_AUDIT_WEBHOOK_URL=http://127.0.0.1:9999/ingest
    set FINSENTINEL_AUDIT_WEBHOOK_TOKEN=<same token as above>
    .\\venv-security\\Scripts\\python.exe scripts\\run_dev.py

Environment variables
---------------------
  FINSENTINEL_AUDIT_WEBHOOK_TOKEN   Required. Bearer token for auth.
  FINSENTINEL_SIEM_LOG              JSONL output path (default: logs/finsentinel-siem.jsonl)
  FINSENTINEL_FORWARDER_PORT        Listening port (default: 9999)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s siem-forwarder %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("siem_forwarder")

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_SIEM_LOG = REPO_ROOT / "logs" / "finsentinel-siem.jsonl"
SIEM_LOG = Path(os.environ.get("FINSENTINEL_SIEM_LOG", str(DEFAULT_SIEM_LOG)))
PORT = int(os.environ.get("FINSENTINEL_FORWARDER_PORT", "9999"))

_TOKEN = os.environ.get("FINSENTINEL_AUDIT_WEBHOOK_TOKEN", "").strip()
if not _TOKEN:
    sys.exit(
        "ERROR: FINSENTINEL_AUDIT_WEBHOOK_TOKEN is not set.\n"
        "Set it in your shell before starting the forwarder:\n"
        "  set FINSENTINEL_AUDIT_WEBHOOK_TOKEN=<your-secret-token>"
    )

_seen_keys: set[str] = set()

SIEM_LOG.parent.mkdir(parents=True, exist_ok=True)


def _verify_token(auth_header: str | None) -> bool:
    if not auth_header:
        return False
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    # Constant-time compare — prevents timing-based token discovery.
    return hmac.compare_digest(
        hashlib.sha256(parts[1].encode()).digest(),
        hashlib.sha256(_TOKEN.encode()).digest(),
    )


def _outbox_to_siem(payload: dict) -> dict:
    """Map outbox delivery payload → SIEM JSONL record.

    ``source`` is the anchor field the Wazuh base rule (100100) matches on;
    events are parsed by Wazuh's built-in JSON decoder (log_format json).
    """
    return {
        "source": "finsentinel",
        "service": payload.get("service", ""),
        "event_id": payload.get("event_id", ""),
        "idempotency_key": payload.get("idempotency_key", ""),
        "timestamp": payload.get("created_at", ""),
        "event_type": payload.get("event_type", ""),
        "severity": payload.get("severity", ""),
        "client_id": payload.get("client_id") or "",
        "update_id": payload.get("update_id") or "",
        "description": payload.get("description", ""),
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass  # suppress default access log; we write our own

    def do_POST(self) -> None:
        if self.path != "/ingest":
            self._send(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self.close_connection = True
            self._send(400, {"error": "invalid content-length"})
            return
        if length < 0 or length > 1_000_000:
            self.close_connection = True
            self._send(413, {"error": "payload too large"})
            return

        # Read the (size-bounded) body before replying so the client always
        # receives a clean HTTP status instead of a connection reset.
        body = self.rfile.read(length)

        auth = self.headers.get("Authorization")
        if not _verify_token(auth):
            logger.warning("401 from %s — bad or missing token", self.client_address[0])
            self._send(401, {"error": "unauthorized"})
            return

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self._send(400, {"error": "invalid json"})
            return
        if not isinstance(payload, dict):
            self._send(400, {"error": "json object expected"})
            return

        ikey = payload.get("idempotency_key", "")
        if not ikey:
            self._send(400, {"error": "missing idempotency_key"})
            return

        if ikey in _seen_keys:
            logger.info("duplicate idempotency_key=%s — skipped", ikey)
            self._send(200, {"status": "duplicate"})
            return

        record = _outbox_to_siem(payload)
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))

        try:
            with SIEM_LOG.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            logger.error("failed to write SIEM log: %s", exc)
            self._send(500, {"error": "write failed"})
            return

        _seen_keys.add(ikey)
        logger.info(
            "wrote event_type=%s severity=%s client_id=%s",
            record["event_type"],
            record["severity"],
            record["client_id"] or "(none)",
        )
        self._send(200, {"status": "ok"})

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    server = HTTPServer(("127.0.0.1", PORT), _Handler)
    logger.info(
        "FinSentinel SIEM forwarder listening on http://127.0.0.1:%d/ingest", PORT
    )
    logger.info("Writing JSONL to: %s", SIEM_LOG)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
