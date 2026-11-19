
"""Tests for the operator approval/rejection HTTP API."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from enforcement.approval_service import (
    UpdateStatus,
    clear_approval_registry,
    get_update_record,
    record_ingestion_audit_result,
    register_validated_update,
)
from ingestion.sample_count_provider import PROVENANCE_CLIENT_CLAIMED, SampleCountResult

client = TestClient(app)

APPROVE_URL = "/api/v1/updates/{client_id}/{update_id}/approve"
REJECT_URL = "/api/v1/updates/{client_id}/{update_id}/reject"
QUARANTINE_URL = "/api/v1/updates/{client_id}/{update_id}/quarantine"
STATUS_URL = "/api/v1/updates/{client_id}/{update_id}/status"
PENDING_URL = "/api/v1/updates/pending"

TEST_TOKEN = "test-operator-token-abc123"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_TOKEN}"}
TEST_DIGEST = "b" * 64


@pytest.fixture(autouse=True)
def reset_approval_registry():
    clear_approval_registry()
    yield
    clear_approval_registry()


def _register_pending(
    *,
    update_id: str = "u-001",
    client_id: str = "c-001",
    model_version: str = "cnn-v1",
    round_number: int = 1,
    sample_count: int = 1,
    payload_sha256: str = TEST_DIGEST,
) -> None:
    register_validated_update(
        update_id=update_id,
        client_id=client_id,
        model_version=model_version,
        round_number=round_number,
        sample_count_result=SampleCountResult(
            count=sample_count, provenance=PROVENANCE_CLIENT_CLAIMED
        ),
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
# Authentication tests
# ---------------------------------------------------------------------------

def test_no_token_configured_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINSENTINEL_OPERATOR_TOKEN", raising=False)
    _register_pending()
    response = client.get(
        STATUS_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_missing_auth_header_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    response = client.get(
        STATUS_URL.format(client_id="c-001", update_id="u-001"),
    )
    assert response.status_code == 401


def test_wrong_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    response = client.get(
        STATUS_URL.format(client_id="c-001", update_id="u-001"),
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /updates/{client_id}/{update_id}/status
# ---------------------------------------------------------------------------

def test_status_returns_pending_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    response = client.get(
        STATUS_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["update_id"] == "u-001"
    assert body["client_id"] == "c-001"
    assert body["status"] == UpdateStatus.PENDING_APPROVAL.value
    assert body["payload_sha256"] == TEST_DIGEST


def test_status_unknown_update_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    response = client.get(
        STATUS_URL.format(client_id="c-001", update_id="nonexistent"),
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /updates/{client_id}/{update_id}/approve
# ---------------------------------------------------------------------------

def test_approve_pending_update_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    response = client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Reviewed; weights look nominal."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == UpdateStatus.APPROVED.value
    assert "nominal" in body["reason"]


def test_approve_persists_in_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Looks clean."},
    )
    record = get_update_record(client_id="c-001", update_id="u-001")
    assert record.status == UpdateStatus.APPROVED


def test_approve_unknown_update_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    response = client.post(
        APPROVE_URL.format(client_id="c-001", update_id="nonexistent"),
        headers=AUTH_HEADERS,
        json={"reason": "Approving."},
    )
    assert response.status_code == 409


def test_duplicate_approve_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "First approval."},
    )
    response = client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Second approval attempt."},
    )
    assert response.status_code == 409


def test_approve_requires_non_empty_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    response = client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": ""},
    )
    assert response.status_code == 422


def test_approve_incomplete_evidence_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cannot approve an update that has not had its audit result persisted."""
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    # Register without calling record_ingestion_audit_result
    register_validated_update(
        update_id="u-no-audit",
        client_id="c-001",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=1, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=TEST_DIGEST,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 10.0},
    )
    response = client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-no-audit"),
        headers=AUTH_HEADERS,
        json={"reason": "Approving without audit."},
    )
    assert response.status_code == 409
    detail = response.json()["detail"].lower()
    assert "evidence" in detail or "audit" in detail


# ---------------------------------------------------------------------------
# POST /updates/{client_id}/{update_id}/reject
# ---------------------------------------------------------------------------

def test_reject_pending_update_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    response = client.post(
        REJECT_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Weights deviate from expected distribution."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == UpdateStatus.REJECTED.value


def test_reject_already_approved_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Approved first."},
    )
    response = client.post(
        REJECT_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Now trying to reject."},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# POST /updates/{client_id}/{update_id}/quarantine
# ---------------------------------------------------------------------------

def test_quarantine_pending_update_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    response = client.post(
        QUARANTINE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Flagged for further analysis."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == UpdateStatus.QUARANTINED.value


def test_quarantined_update_cannot_be_approved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quarantined updates cannot re-enter pending_approval and be approved."""
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    client.post(
        QUARANTINE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Quarantining."},
    )
    response = client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Trying to approve quarantined update."},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Multi-update isolation
# ---------------------------------------------------------------------------

def test_different_updates_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending(update_id="u-A", client_id="c-001")
    _register_pending(update_id="u-B", client_id="c-001", payload_sha256="c" * 64)

    client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-A"),
        headers=AUTH_HEADERS,
        json={"reason": "Approving A."},
    )

    record_b = get_update_record(client_id="c-001", update_id="u-B")
    assert record_b.status == UpdateStatus.PENDING_APPROVAL

    client.post(
        REJECT_URL.format(client_id="c-001", update_id="u-B"),
        headers=AUTH_HEADERS,
        json={"reason": "Rejecting B."},
    )

    record_a = get_update_record(client_id="c-001", update_id="u-A")
    assert record_a.status == UpdateStatus.APPROVED


# ---------------------------------------------------------------------------
# GET /updates/pending
# ---------------------------------------------------------------------------

def test_pending_list_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    response = client.get(PENDING_URL)
    assert response.status_code == 401


def test_pending_list_returns_503_when_no_token_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FINSENTINEL_OPERATOR_TOKEN", raising=False)
    response = client.get(PENDING_URL, headers=AUTH_HEADERS)
    assert response.status_code == 503


def test_pending_list_empty_initially(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    response = client.get(PENDING_URL, headers=AUTH_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["pending"] == []


def test_pending_list_returns_registered_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    response = client.get(PENDING_URL, headers=AUTH_HEADERS)
    assert response.status_code == 200
    items = response.json()["pending"]
    assert len(items) == 1
    item = items[0]
    assert item["update_id"] == "u-001"
    assert item["client_id"] == "c-001"
    assert item["status"] == UpdateStatus.PENDING_APPROVAL.value


def test_pending_list_excludes_approved_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    client.post(
        APPROVE_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Approved."},
    )
    response = client.get(PENDING_URL, headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["pending"] == []


def test_pending_list_excludes_rejected_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending()
    client.post(
        REJECT_URL.format(client_id="c-001", update_id="u-001"),
        headers=AUTH_HEADERS,
        json={"reason": "Rejected."},
    )
    response = client.get(PENDING_URL, headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["pending"] == []


def test_pending_list_multiple_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    _register_pending(update_id="u-A", client_id="c-001")
    _register_pending(update_id="u-B", client_id="c-002", payload_sha256="e" * 64)
    response = client.get(PENDING_URL, headers=AUTH_HEADERS)
    assert response.status_code == 200
    ids = {item["update_id"] for item in response.json()["pending"]}
    assert ids == {"u-A", "u-B"}
