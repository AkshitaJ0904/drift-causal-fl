"""Sprint 6: Operator dashboard endpoint tests.

Covers:
- 401 when Authorization header is absent
- 401 when token is wrong
- 503 when FINSENTINEL_OPERATOR_TOKEN is unset
- 200 success: response contains all expected sections
- outbox.alert is True when dead_letter_count > 0
- outbox.alert is False when dead_letter_count == 0
- No credentials or key material in response
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
_TOKEN = "dashboard-test-operator-token"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture(autouse=True)
def _set_operator_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", _TOKEN)
    yield


# ---------------------------------------------------------------------------
# Authentication guard
# ---------------------------------------------------------------------------

def test_dashboard_no_auth_returns_401():
    resp = client.get("/api/v1/operator/dashboard")
    assert resp.status_code == 401


def test_dashboard_wrong_token_returns_401():
    resp = client.get(
        "/api/v1/operator/dashboard",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


def test_dashboard_no_token_configured_returns_503(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FINSENTINEL_OPERATOR_TOKEN", raising=False)
    resp = client.get(
        "/api/v1/operator/dashboard",
        headers={"Authorization": "Bearer anything"},
    )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------

def test_dashboard_returns_all_sections(_sqlite_test_database):
    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert "outbox" in body
    assert "registries" in body
    assert "approvals" in body
    assert "worker" in body
    assert "config" in body


def test_dashboard_outbox_section_has_expected_keys(_sqlite_test_database):
    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200

    outbox = resp.json()["outbox"]
    assert "pending_count" in outbox
    assert "dead_letter_count" in outbox
    assert "alert" in outbox


def test_dashboard_outbox_alert_false_when_no_dead_letters(_sqlite_test_database):
    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200

    body = resp.json()
    assert body["outbox"]["alert"] is False
    assert body["outbox"]["dead_letter_count"] == 0


def test_dashboard_outbox_alert_true_when_dead_letters_exist(_sqlite_test_database):
    from sqlalchemy import delete

    from audit.delivery import DeliveryPermanentError
    from audit.outbox import deliver_pending_events, enqueue
    from core.supabase.session import SessionLocal
    from db.models.audit_outbox import AuditOutboxRecord

    # Clear outbox first.
    with SessionLocal() as db:
        db.execute(delete(AuditOutboxRecord))
        db.commit()

    # Enqueue and dead-letter a record.
    with SessionLocal() as db:
        with db.begin():
            enqueue(
                db,
                event_id=None,
                event_type="key.registered",
                severity="info",
                client_id="cl-1",
                update_id=None,
                description="dashboard test",
            )
            db.flush()

    def _permanent_fail(payload):
        raise DeliveryPermanentError("HTTP 401")

    deliver_pending_events(delivery_fn=_permanent_fail)

    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200

    body = resp.json()
    assert body["outbox"]["alert"] is True
    assert body["outbox"]["dead_letter_count"] == 1

    # Cleanup.
    with SessionLocal() as db:
        db.execute(delete(AuditOutboxRecord))
        db.commit()


def test_dashboard_config_section_no_token_in_response(_sqlite_test_database):
    """The dashboard must never return the actual operator token value."""
    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200

    body_text = resp.text
    assert _TOKEN not in body_text, (
        "Operator token value must not appear in the dashboard response."
    )


def test_dashboard_registries_section_has_counts(_sqlite_test_database):
    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200

    registries = resp.json()["registries"]
    # Counts may be 0 or None (if DB unavailable), but the keys must be present.
    assert "trusted_key_count" in registries
    assert "model_schema_count" in registries


def test_dashboard_worker_section_reflects_env(
    monkeypatch: pytest.MonkeyPatch,
    _sqlite_test_database,
):
    monkeypatch.setenv("FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED", "true")
    monkeypatch.setenv("FINSENTINEL_AUDIT_WEBHOOK_URL", "https://siem.example.com/events")

    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200

    worker = resp.json()["worker"]
    assert worker["enabled"] is True
    assert worker["webhook_configured"] is True


def test_dashboard_approvals_pending_count_reflects_pending_approval_status(
    _sqlite_test_database,
):
    """Regression: dashboard must count status='pending_approval', not 'pending'."""
    from enforcement.approval_service import (
        clear_approval_registry,
        record_ingestion_audit_result,
        register_validated_update,
    )
    from ingestion.sample_count_provider import PROVENANCE_CLIENT_CLAIMED, SampleCountResult

    clear_approval_registry()
    try:
        register_validated_update(
            update_id="dash-u-001",
            client_id="dash-c-001",
            model_version="cnn-v1",
            round_number=1,
            sample_count_result=SampleCountResult(
                count=10, provenance=PROVENANCE_CLIENT_CLAIMED
            ),
            payload_sha256="f" * 64,
            risk_score=0,
            risk_severity="LOW",
            suspicious=False,
            anomaly_reasons=(),
            detector_version="test-v1",
            detector_config={"t": 1.0},
        )
        record_ingestion_audit_result(
            client_id="dash-c-001",
            update_id="dash-u-001",
            audit_status="persisted",
            audit_failures=(),
        )

        resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
        assert resp.status_code == 200
        approvals = resp.json()["approvals"]
        assert approvals["pending_count"] == 1, (
            f"Expected 1 pending approval, got {approvals['pending_count']!r}. "
            "Dashboard may be filtering on wrong status value."
        )
    finally:
        clear_approval_registry()


# ---------------------------------------------------------------------------
# Detection section (Entry 56)
# ---------------------------------------------------------------------------

def test_dashboard_returns_detection_section(_sqlite_test_database):
    """Dashboard response must include a 'detection' section (Entry 56)."""
    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert "detection" in body, (
        "Dashboard response missing 'detection' section. "
        "api/dashboard.py must include the detection thresholds block."
    )


def test_dashboard_detection_section_has_expected_keys(_sqlite_test_database):
    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200

    detection = resp.json()["detection"]
    assert "thresholds" in detection
    assert "error" in detection
    assert "high_risk_action" in detection


def test_dashboard_detection_high_risk_action_default(
    monkeypatch: pytest.MonkeyPatch,
    _sqlite_test_database,
):
    """When FINSENTINEL_HIGH_RISK_ACTION is unset, default is 'quarantined'."""
    monkeypatch.delenv("FINSENTINEL_HIGH_RISK_ACTION", raising=False)

    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200

    detection = resp.json()["detection"]
    assert detection["high_risk_action"] == "quarantined"


def test_dashboard_detection_high_risk_action_env(
    monkeypatch: pytest.MonkeyPatch,
    _sqlite_test_database,
):
    """FINSENTINEL_HIGH_RISK_ACTION env var is reflected in detection.high_risk_action."""
    monkeypatch.setenv("FINSENTINEL_HIGH_RISK_ACTION", "pending_approval")

    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200

    detection = resp.json()["detection"]
    assert detection["high_risk_action"] == "pending_approval"


def test_dashboard_detection_thresholds_present_in_test_mode(_sqlite_test_database):
    """In ENVIRONMENT=test mode, get_detection_config() returns synthetic defaults.
    The dashboard detection.thresholds must not be None."""
    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200

    detection = resp.json()["detection"]
    assert detection["error"] is None, (
        f"Unexpected detection error in test mode: {detection['error']}"
    )
    assert detection["thresholds"] is not None, (
        "detection.thresholds should be a dict in test mode (synthetic defaults apply)"
    )
    thresholds = detection["thresholds"]
    assert "max_weight_l2_norm" in thresholds
    assert "max_update_l2_norm" in thresholds
    assert "max_weight_abs_mean" in thresholds
    assert "max_weight_std" in thresholds
    assert "max_weight_zero_fraction" in thresholds
    assert "min_weight_zero_fraction" in thresholds


def test_dashboard_detection_no_secrets_in_response(_sqlite_test_database):
    """Detection section must not contain credentials or key material."""
    resp = client.get("/api/v1/operator/dashboard", headers=_HEADERS)
    assert resp.status_code == 200

    detection_text = str(resp.json()["detection"])
    # Operator token must never appear
    assert _TOKEN not in detection_text
