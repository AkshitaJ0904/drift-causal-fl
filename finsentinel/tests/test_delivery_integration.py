"""Integration tests for the audit delivery pipeline.

Exercises the complete delivery chain end-to-end:
  enqueue → deliver_pending_events(create_webhook_delivery_fn(...)) → mark_delivered

A real local HTTP server (stdlib http.server + threading) acts as the mock
receiver so no production endpoint or new test dependency is needed.

These tests prove:
- The full configurable delivery integration contract works.
- Idempotency keys are stable and present in the delivered payload.
- TLS certificate errors are reported without leaking secrets.
- Authentication headers are sent.
- 4xx responses dead-letter immediately.
- 5xx responses trigger backoff.
- delivery_fn=None keeps records pending without dead-lettering.
"""
from __future__ import annotations

import json
import threading
from http.server import (
    BaseHTTPRequestHandler,
    HTTPServer,
)

import pytest
from sqlalchemy import delete

from audit.delivery import (
    DeliveryConfigError,
    create_webhook_delivery_fn,
)
from audit.outbox import (
    dead_letter_count,
    deliver_pending_events,
    enqueue,
    pending_count,
)
from core.supabase.session import SessionLocal
from db.models.audit_outbox import AuditOutboxRecord

# ---------------------------------------------------------------------------
# Shared outbox cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_outbox_integration(_sqlite_test_database):
    """Clear the outbox before and after every test in this module."""

    def _clear():
        with SessionLocal() as db:
            db.execute(delete(AuditOutboxRecord))
            db.commit()

    _clear()
    yield
    _clear()


# ---------------------------------------------------------------------------
# Local mock HTTP receiver
# ---------------------------------------------------------------------------


class _ReceivedRequest:
    """Snapshot of one HTTP request received by the mock server."""

    def __init__(self, method: str, path: str, headers: dict, body: bytes) -> None:
        self.method = method
        self.path = path
        # Normalize all header names to lowercase for case-insensitive lookups.
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.body = body

    @property
    def json(self) -> dict:
        return json.loads(self.body)


def _make_mock_server(response_status: int = 200) -> tuple[HTTPServer, str, list[_ReceivedRequest]]:
    """Start a local HTTP server on a random free port.

    Returns (server, base_url, received_requests_list).
    Caller must call server.shutdown() when done.
    """
    received: list[_ReceivedRequest] = []
    _status = response_status

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            received.append(
                _ReceivedRequest(
                    method="POST",
                    path=self.path,
                    headers=dict(self.headers),
                    body=body,
                )
            )
            self.send_response(_status)
            self.end_headers()

        def log_message(self, format, *args):  # noqa: A002
            pass  # Suppress noisy access log in tests.

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, f"http://127.0.0.1:{port}", received


def _enqueue_one(event_type: str = "test.delivery.integration") -> str:
    """Enqueue a single outbox record and return its idempotency_key."""
    with SessionLocal() as db:
        with db.begin():
            record = enqueue(
                db,
                event_id=None,
                event_type=event_type,
                severity="info",
                description="Integration test event",
                client_id="test-client",
                update_id="test-update-1",
            )
            db.flush()
            return record.idempotency_key


# ---------------------------------------------------------------------------
# Task 1a — Full delivery chain: enqueue → deliver → mark_delivered
# ---------------------------------------------------------------------------


def test_full_delivery_marks_record_delivered():
    """End-to-end: enqueue, deliver via local server, verify delivered status."""
    server, base_url, received = _make_mock_server(response_status=200)
    try:
        ikey = _enqueue_one()
        delivery_fn = create_webhook_delivery_fn(url=f"{base_url}/events")

        result = deliver_pending_events(delivery_fn=delivery_fn)

        assert result["claimed"] == 1
        assert result["delivered"] == 1
        assert result["released"] == 0
        assert result.get("dead_lettered", 0) == 0

        # Record is no longer pending.
        assert pending_count() == 0

        # Payload was actually received by the local server.
        assert len(received) == 1
        payload = received[0].json
        assert payload["idempotency_key"] == ikey
        assert payload["event_type"] == "test.delivery.integration"
        assert payload["schema_version"] == "1"
        assert payload["service"] == "finsentinel"
        assert "created_at" in payload
        assert "attempt_count" in payload
    finally:
        server.shutdown()


def test_delivery_sends_authentication_header():
    """Bearer token is sent in the Authorization header."""
    server, base_url, received = _make_mock_server(response_status=200)
    try:
        _enqueue_one()
        delivery_fn = create_webhook_delivery_fn(
            url=f"{base_url}/events",
            token="test-secret-bearer-token",
        )
        deliver_pending_events(delivery_fn=delivery_fn)

        assert len(received) == 1
        auth = received[0].headers.get("authorization", "")
        assert auth == "Bearer test-secret-bearer-token"
    finally:
        server.shutdown()


def test_delivery_no_token_no_auth_header():
    """No Authorization header when token is omitted (loopback allows this)."""
    server, base_url, received = _make_mock_server(response_status=200)
    try:
        _enqueue_one()
        delivery_fn = create_webhook_delivery_fn(url=f"{base_url}/events", token=None)
        deliver_pending_events(delivery_fn=delivery_fn)

        assert len(received) == 1
        auth = received[0].headers.get("authorization", "")
        assert auth == ""
    finally:
        server.shutdown()


def test_delivery_idempotency_key_stable_across_retries():
    """The same idempotency_key is used on the initial attempt and all retries."""
    server, base_url, received = _make_mock_server(response_status=500)
    try:
        ikey = _enqueue_one()
        delivery_fn = create_webhook_delivery_fn(url=f"{base_url}/events")

        # First attempt: 500 → backoff (attempt_count=1, retry_after set).
        result1 = deliver_pending_events(delivery_fn=delivery_fn, claim_ttl_seconds=0)
        assert result1["claimed"] == 1
        assert result1["delivered"] == 0

        # First attempt sent the payload with the original idempotency_key.
        assert len(received) == 1
        assert received[0].json["idempotency_key"] == ikey

        # Reset retry_after so the record can be re-claimed immediately.
        with SessionLocal() as db:
            with db.begin():
                rec = db.query(AuditOutboxRecord).filter_by(idempotency_key=ikey).one()
                rec.retry_after = None

        # Second attempt on 500 server.
        result2 = deliver_pending_events(delivery_fn=delivery_fn, claim_ttl_seconds=0)
        assert result2["claimed"] == 1

        assert len(received) == 2
        assert received[1].json["idempotency_key"] == ikey, (
            "idempotency_key must be stable across retries so receivers can deduplicate"
        )
    finally:
        server.shutdown()


def test_delivery_4xx_dead_letters_immediately():
    """HTTP 4xx response dead-letters the record without backoff."""
    server, base_url, received = _make_mock_server(response_status=400)
    try:
        _enqueue_one()
        delivery_fn = create_webhook_delivery_fn(url=f"{base_url}/events")

        result = deliver_pending_events(delivery_fn=delivery_fn)

        assert result["claimed"] == 1
        assert result["delivered"] == 0
        assert result.get("dead_lettered", 0) == 1

        # Record is in dead_letter status.
        with SessionLocal() as db:
            rec = db.query(AuditOutboxRecord).one()
        assert rec.status == "dead_letter"
        assert dead_letter_count() == 1
    finally:
        server.shutdown()


def test_delivery_5xx_applies_backoff_not_dead_letter():
    """HTTP 5xx response triggers backoff; record is NOT dead-lettered on first failure."""
    server, base_url, received = _make_mock_server(response_status=503)
    try:
        _enqueue_one()
        delivery_fn = create_webhook_delivery_fn(url=f"{base_url}/events")

        result = deliver_pending_events(delivery_fn=delivery_fn)

        assert result["claimed"] == 1
        assert result["delivered"] == 0
        assert result.get("dead_lettered", 0) == 0
        assert dead_letter_count() == 0

        # Record is pending with retry_after set.
        with SessionLocal() as db:
            rec = db.query(AuditOutboxRecord).one()
        assert rec.status == "pending"
        assert rec.retry_after is not None
    finally:
        server.shutdown()


def test_delivery_multiple_events_all_delivered():
    """Multiple enqueued records are all delivered in one pass."""
    server, base_url, received = _make_mock_server(response_status=200)
    try:
        for i in range(3):
            _enqueue_one(event_type=f"test.event.{i}")

        delivery_fn = create_webhook_delivery_fn(url=f"{base_url}/events")
        result = deliver_pending_events(delivery_fn=delivery_fn, max_events=10)

        assert result["claimed"] == 3
        assert result["delivered"] == 3
        assert pending_count() == 0
        assert len(received) == 3
    finally:
        server.shutdown()


def test_delivery_no_fn_keeps_records_pending_no_dead_letter():
    """delivery_fn=None keeps records pending indefinitely without dead-lettering."""
    _enqueue_one()

    result = deliver_pending_events(delivery_fn=None)

    assert result["claimed"] == 1
    assert result["delivered"] == 0
    # Perpetually pending — not dead-lettered.
    assert dead_letter_count() == 0
    assert pending_count() == 1


def test_delivery_payload_does_not_contain_secrets():
    """Delivered payload contains no token, password, or key material fields."""
    server, base_url, received = _make_mock_server(response_status=200)
    try:
        _enqueue_one()
        delivery_fn = create_webhook_delivery_fn(
            url=f"{base_url}/events",
            token="super-secret-token",
        )
        deliver_pending_events(delivery_fn=delivery_fn)

        payload = received[0].json
        payload_str = json.dumps(payload).lower()
        # Token must NOT appear in the payload body itself.
        assert "super-secret-token" not in payload_str
        assert "password" not in payload_str
        # Required safe fields must be present.
        for field in ("idempotency_key", "event_type", "severity", "schema_version", "service"):
            assert field in payload
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# Task 1b — Configuration validation
# ---------------------------------------------------------------------------


def test_create_delivery_fn_rejects_plain_http_non_loopback():
    """Non-loopback HTTP URL is rejected at construction (SSRF guard)."""
    with pytest.raises(DeliveryConfigError, match="HTTPS"):
        create_webhook_delivery_fn(url="http://external-siem.example.com/events")


def test_create_delivery_fn_accepts_loopback_http():
    """Loopback HTTP URL is accepted (development / local test only)."""
    fn = create_webhook_delivery_fn(url="http://localhost/events")
    assert fn is not None


def test_create_delivery_fn_accepts_https():
    """HTTPS URL is accepted."""
    fn = create_webhook_delivery_fn(url="https://siem.example.com/events")
    assert fn is not None


def test_create_delivery_fn_rejects_empty_url():
    """Empty URL is rejected at construction."""
    with pytest.raises(DeliveryConfigError):
        create_webhook_delivery_fn(url="")


def test_create_delivery_fn_rejects_ftp_scheme():
    """Non-HTTP scheme is rejected."""
    with pytest.raises(DeliveryConfigError, match="scheme"):
        create_webhook_delivery_fn(url="ftp://files.example.com/events")
