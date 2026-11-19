
"""Security-focused negative tests for the operator approval API.

Covers path parameter validation (length limits, control characters),
request body validation, invalid state transitions, and audit-event
behavior.  Positive-path coverage lives in test_operator_approval_api.py.
"""

import urllib.parse
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.main import app
from core.supabase.session import SessionLocal
from db.models.audit_event import AuditEvent
from enforcement.approval_service import (
    UpdateStatus,
    approve_update,
    clear_approval_registry,
    record_ingestion_audit_result,
    register_validated_update,
)
from ingestion.sample_count_provider import PROVENANCE_CLIENT_CLAIMED, SampleCountResult

client = TestClient(app)

TEST_TOKEN = "test-operator-security-token"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_TOKEN}"}
TEST_DIGEST = "a" * 64

APPROVE_URL = "/api/v1/updates/{client_id}/{update_id}/approve"
REJECT_URL = "/api/v1/updates/{client_id}/{update_id}/reject"
QUARANTINE_URL = "/api/v1/updates/{client_id}/{update_id}/quarantine"
STATUS_URL = "/api/v1/updates/{client_id}/{update_id}/status"


def _clear_audit_events() -> None:
    with SessionLocal() as db:
        with db.begin():
            db.execute(delete(AuditEvent))


@pytest.fixture(autouse=True)
def reset_registry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    clear_approval_registry()
    _clear_audit_events()
    yield
    clear_approval_registry()
    _clear_audit_events()


def _register_and_approve(
    *,
    update_id: str = "u-001",
    client_id: str = "c-001",
    payload_sha256: str = TEST_DIGEST,
) -> None:
    register_validated_update(
        update_id=update_id,
        client_id=client_id,
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=1, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=payload_sha256,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 10.0},
    )
    record_ingestion_audit_result(
        client_id=client_id,
        update_id=update_id,
        audit_status="persisted",
        audit_failures=(),
    )
    approve_update(client_id=client_id, update_id=update_id, reason="approved for security test")


def _register_pending(
    *,
    update_id: str = "u-001",
    client_id: str = "c-001",
    payload_sha256: str = TEST_DIGEST,
) -> None:
    register_validated_update(
        update_id=update_id,
        client_id=client_id,
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=1, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=payload_sha256,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 10.0},
    )
    record_ingestion_audit_result(
        client_id=client_id,
        update_id=update_id,
        audit_status="persisted",
        audit_failures=(),
    )


# ---------------------------------------------------------------------------
# Path parameter validation
# ---------------------------------------------------------------------------

def test_client_id_too_long_returns_422() -> None:
    long_id = "c" * 129
    response = client.get(
        STATUS_URL.format(client_id=long_id, update_id="u-001"),
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422
    assert "client_id" in response.json()["detail"]


def test_update_id_too_long_returns_422() -> None:
    long_id = "u" * 129
    response = client.get(
        STATUS_URL.format(client_id="c-001", update_id=long_id),
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422
    assert "update_id" in response.json()["detail"]


def test_control_char_in_client_id_returns_422() -> None:
    bad_id = urllib.parse.quote("\x01bad", safe="")
    response = client.get(
        f"/api/v1/updates/{bad_id}/u-001/status",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


def test_control_char_in_update_id_returns_422() -> None:
    bad_id = urllib.parse.quote("\x01bad", safe="")
    response = client.get(
        f"/api/v1/updates/c-001/{bad_id}/status",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Request body validation
# ---------------------------------------------------------------------------

def test_reason_too_long_returns_422() -> None:
    _register_pending()
    response = client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "x" * 2001},
    )
    assert response.status_code == 422


def test_extra_body_field_returns_422() -> None:
    _register_pending()
    response = client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Valid reason.", "unexpected_field": "value"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Invalid state transitions
# ---------------------------------------------------------------------------

def test_approved_cannot_be_rejected() -> None:
    _register_and_approve()
    response = client.post(
        REJECT_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Trying to reject approved update."},
    )
    assert response.status_code == 409


def test_approved_cannot_be_quarantined() -> None:
    _register_and_approve()
    response = client.post(
        QUARANTINE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Trying to quarantine approved update."},
    )
    assert response.status_code == 409


def test_rejected_cannot_be_approved() -> None:
    _register_pending()
    client.post(
        REJECT_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Rejecting first."},
    )
    response = client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Now trying to approve."},
    )
    assert response.status_code == 409


def test_rejected_cannot_be_quarantined() -> None:
    _register_pending()
    client.post(
        REJECT_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Rejecting first."},
    )
    response = client.post(
        QUARANTINE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Now trying to quarantine."},
    )
    assert response.status_code == 409


def test_quarantined_cannot_be_rejected() -> None:
    _register_pending()
    client.post(
        QUARANTINE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Quarantining first."},
    )
    response = client.post(
        REJECT_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Now trying to reject."},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Cross-client identity isolation
# ---------------------------------------------------------------------------

def test_client_a_decision_does_not_affect_client_b() -> None:
    """Approving client A's update does not change client B's update status."""
    _register_pending(update_id="u-001", client_id="c-001")
    _register_pending(update_id="u-001", client_id="c-002", payload_sha256="b" * 64)

    client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Approving c-001."},
    )

    response = client.get(
        STATUS_URL.format(client_id="c-002", update_id="u-001"),
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == UpdateStatus.PENDING_APPROVAL.value


# ---------------------------------------------------------------------------
# Audit severity
# ---------------------------------------------------------------------------

def test_approve_requested_audit_event_has_info_severity() -> None:
    """The pre-decision 'approve_requested' event carries severity='info'.

    State-change events ('operator.update_approved') are written atomically in
    the service layer via db.add(), not through record_audit_event, and are
    verified separately in test_approval_writes_state_change_audit_event.
    """
    _register_pending()
    captured: list[dict[str, Any]] = []

    def fake_record_audit_event(**kwargs: Any) -> None:  # type: ignore[misc]
        captured.append(kwargs)

    with patch("api.approval.record_audit_event", side_effect=fake_record_audit_event):
        response = client.post(
            APPROVE_URL.format(client_id="c-001", update_id="u-001"),
            headers=AUTH_HEADERS,
            json={"reason": "Looks clean."},
        )

    assert response.status_code == 200
    severities = {ev["event_type"]: ev["severity"] for ev in captured}
    assert severities.get("operator.approve_requested") == "info"


def test_reject_requested_audit_event_has_high_severity() -> None:
    """The pre-decision 'reject_requested' event carries severity='high'.

    State-change events ('operator.update_rejected') are written atomically in
    the service layer via db.add(), not through record_audit_event.
    """
    _register_pending()
    captured: list[dict[str, Any]] = []

    def fake_record_audit_event(**kwargs: Any) -> None:  # type: ignore[misc]
        captured.append(kwargs)

    with patch("api.approval.record_audit_event", side_effect=fake_record_audit_event):
        response = client.post(
            REJECT_URL.format(client_id="c-001", update_id="u-001"),
            headers=AUTH_HEADERS,
            json={"reason": "Looks suspicious."},
        )

    assert response.status_code == 200
    severities = {ev["event_type"]: ev["severity"] for ev in captured}
    assert severities.get("operator.reject_requested") == "high"


def test_approval_writes_state_change_audit_event() -> None:
    """Every approval writes an 'operator.update_approved' audit event atomically.

    The audit event is written inside the same DB transaction as the state
    transition, so both are durable together.  This holds for API callers and
    direct service-layer callers alike — the HTTP pre-decision event
    ('approve_requested') is recorded separately by the HTTP handler, but the
    state-change event is always written by the service layer.
    """
    _register_pending()
    response = client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Approving; verifying audit trail."},
    )
    assert response.status_code == 200
    assert response.json()["status"] == UpdateStatus.APPROVED.value

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == "c-001",
                AuditEvent.update_id == "u-001",
                AuditEvent.event_type == "operator.update_approved",
            )
        ).all()
    assert len(events) == 1
    assert events[0].severity == "info"


def test_pre_decision_audit_failure_blocks_approval_with_503() -> None:
    """Pre-decision audit failure must block the approval and return 503.

    When the audit service is unavailable before the decision executes, the
    endpoint returns 503 and the update remains in pending_approval.
    No unaudited state transition is allowed.
    """
    _register_pending()

    def raise_on_any_audit(**kwargs: Any) -> None:  # type: ignore[misc]
        raise RuntimeError("Simulated audit service failure")

    with patch("api.approval.record_audit_event", side_effect=raise_on_any_audit):
        response = client.post(
            APPROVE_URL.format(client_id="c-001", update_id="u-001"),
            headers=AUTH_HEADERS,
            json={"reason": "Approving but audit is down."},
        )

    assert response.status_code == 503
    # The update must still be in pending_approval — no transition was made.
    status_response = client.get(
        STATUS_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == UpdateStatus.PENDING_APPROVAL.value


def test_pre_decision_audit_failure_blocks_rejection_with_503() -> None:
    """Pre-decision audit failure must block rejection and return 503."""
    _register_pending()

    def raise_on_any_audit(**kwargs: Any) -> None:  # type: ignore[misc]
        raise RuntimeError("Simulated audit service failure")

    with patch("api.approval.record_audit_event", side_effect=raise_on_any_audit):
        response = client.post(
            REJECT_URL.format(client_id="c-001", update_id="u-001"),
            headers=AUTH_HEADERS,
            json={"reason": "Rejecting but audit is down."},
        )

    assert response.status_code == 503
    status_response = client.get(
        STATUS_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == UpdateStatus.PENDING_APPROVAL.value
