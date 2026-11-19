"""Tests for the GET /health/alerts monitoring integration endpoint.

Coverage:
- Returns 200 with status="ok" and empty alerts list when no dead letters.
- Returns 200 with status="degraded" and a dead_letter_accumulation alert.
- Alert schema: type, severity, count, message fields present.
- Returns 200 (not an error status code) even when status="degraded".
- Outbox backend failure produces an outbox_unavailable critical alert.
- No authentication required (monitoring agents can poll without credentials).
- Response contains no token, password, or key material.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from api.health import router as health_router
from audit.outbox import enqueue
from core.supabase.session import SessionLocal
from db.models.audit_outbox import AuditOutboxRecord


@pytest.fixture()
def _client():
    app = FastAPI()
    app.include_router(health_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_outbox_alerts(_sqlite_test_database):
    def _clear():
        with SessionLocal() as db:
            db.execute(delete(AuditOutboxRecord))
            db.commit()

    _clear()
    yield
    _clear()


def _enqueue_dead_letter():
    """Enqueue a record and manually set it to dead_letter status."""
    with SessionLocal() as db:
        with db.begin():
            record = enqueue(
                db,
                event_id=None,
                event_type="test.alert",
                severity="info",
                description="dead letter test",
                client_id="test-client",
                update_id="test-update-alert",
            )
            db.flush()
            record.status = "dead_letter"
            record.attempt_count = 10


def test_alerts_ok_when_no_dead_letters(_client):
    """No alerts and status=ok when the dead-letter queue is empty."""
    resp = _client.get("/health/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["alerts"] == []


def test_alerts_no_auth_required(_client):
    """Endpoint is accessible without an Authorization header."""
    resp = _client.get("/health/alerts")
    assert resp.status_code == 200


def test_alerts_degraded_when_dead_letters_exist(_client):
    """status=degraded with dead_letter_accumulation alert when DL count > 0."""
    _enqueue_dead_letter()

    resp = _client.get("/health/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert len(body["alerts"]) == 1
    alert = body["alerts"][0]
    assert alert["type"] == "dead_letter_accumulation"
    assert alert["count"] == 1


def test_alerts_still_200_when_degraded(_client):
    """HTTP 200 is returned even in degraded state so monitors can read the body."""
    _enqueue_dead_letter()

    resp = _client.get("/health/alerts")
    assert resp.status_code == 200


def test_alert_has_required_schema_fields(_client):
    """Every alert object contains type, severity, count, and message."""
    _enqueue_dead_letter()

    body = _client.get("/health/alerts").json()
    for alert in body["alerts"]:
        assert "type" in alert
        assert "severity" in alert
        assert "count" in alert
        assert "message" in alert
        assert isinstance(alert["count"], int)


def test_alert_count_reflects_actual_dead_letters(_client):
    """alert.count matches the actual number of dead-lettered records."""
    for i in range(3):
        with SessionLocal() as db:
            with db.begin():
                record = enqueue(
                    db,
                    event_id=None,
                    event_type="test.alert",
                    severity="info",
                    description=f"dead letter {i}",
                    client_id="test-client",
                    update_id=f"test-update-{i}",
                )
                db.flush()
                record.status = "dead_letter"
                record.attempt_count = 10

    body = _client.get("/health/alerts").json()
    assert body["status"] == "degraded"
    dl_alert = next(a for a in body["alerts"] if a["type"] == "dead_letter_accumulation")
    assert dl_alert["count"] == 3


def test_alert_severity_is_warning_for_dead_letters(_client):
    """Dead-letter alert severity is 'warning' (operator attention, not outage)."""
    _enqueue_dead_letter()

    body = _client.get("/health/alerts").json()
    dl_alert = next(a for a in body["alerts"] if a["type"] == "dead_letter_accumulation")
    assert dl_alert["severity"] == "warning"


def test_alert_message_is_human_readable_string(_client):
    """Alert message is a non-empty human-readable string."""
    _enqueue_dead_letter()

    body = _client.get("/health/alerts").json()
    for alert in body["alerts"]:
        assert isinstance(alert["message"], str)
        assert len(alert["message"]) > 20


def test_alerts_resolves_when_dead_letters_cleared(_client):
    """Status returns to 'ok' once dead-letter records are removed."""
    _enqueue_dead_letter()
    assert _client.get("/health/alerts").json()["status"] == "degraded"

    with SessionLocal() as db:
        db.execute(delete(AuditOutboxRecord).where(AuditOutboxRecord.status == "dead_letter"))
        db.commit()

    body = _client.get("/health/alerts").json()
    assert body["status"] == "ok"
    assert body["alerts"] == []


def test_alerts_outbox_unavailable_returns_critical_alert(_client):
    """If the outbox raises, endpoint returns critical alert (never 500)."""
    with patch("audit.outbox.dead_letter_count", side_effect=RuntimeError("db gone")):
        resp = _client.get("/health/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert any(
        a["type"] == "outbox_unavailable" and a["severity"] == "critical"
        for a in body["alerts"]
    )


def test_alerts_contains_no_secrets(_client):
    """Response body contains no token, password, or key material."""
    _enqueue_dead_letter()
    body_str = _client.get("/health/alerts").text.lower()
    for sensitive in ("password", "token", "secret", "private_key", "credential"):
        assert sensitive not in body_str
