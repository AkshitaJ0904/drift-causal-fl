
"""Tests for the aggregation HTTP API endpoint."""

import base64
import hashlib

import pytest
import torch
from fastapi.testclient import TestClient

from app.main import app
from enforcement.approval_service import (
    approve_update,
    clear_approval_registry,
    record_ingestion_audit_result,
    register_validated_update,
)
from ingestion.sample_count_provider import PROVENANCE_CLIENT_CLAIMED, SampleCountResult
from ingestion.serialization import serialize_state_dict

client = TestClient(app)
ENDPOINT = "/api/v1/aggregation/run"

TEST_TOKEN = "test-operator-token-xyz"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _make_model_payload(weight_val: float = 1.0) -> bytes:
    return serialize_state_dict(
        {
            "layer.weight": torch.tensor([[weight_val, weight_val]], dtype=torch.float32),
            "layer.bias": torch.tensor([0.5], dtype=torch.float32),
        }
    )


@pytest.fixture(autouse=True)
def reset_registry():
    clear_approval_registry()
    yield
    clear_approval_registry()


def _register_and_approve(
    *,
    update_id: str,
    client_id: str = "c-001",
    model_version: str = "cnn-v1",
    round_number: int = 1,
    sample_count: int = 10,
    payload: bytes,
) -> bytes:
    """Register an update and approve it; returns the original payload bytes."""
    sha256 = hashlib.sha256(payload).hexdigest()
    register_validated_update(
        update_id=update_id,
        client_id=client_id,
        model_version=model_version,
        round_number=round_number,
        sample_count_result=SampleCountResult(
            count=sample_count, provenance=PROVENANCE_CLIENT_CLAIMED
        ),
        payload_sha256=sha256,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
    )
    record_ingestion_audit_result(
        client_id=client_id,
        update_id=update_id,
        audit_status="persisted",
        audit_failures=(),
    )
    approve_update(
        client_id=client_id,
        update_id=update_id,
        reason="Approved for aggregation test.",
    )
    return payload


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

def test_aggregation_no_token_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINSENTINEL_OPERATOR_TOKEN", raising=False)
    reference = _make_model_payload()
    payload = _register_and_approve(
        update_id="u-agg-noauth", payload=reference
    )
    response = client.post(
        ENDPOINT,
        headers=AUTH_HEADERS,
        json={
            "model_version": "cnn-v1",
            "round_number": 1,
            "reference_payload_base64": _b64(reference),
            "updates": [
                {
                    "client_id": "c-001",
                    "update_id": "u-agg-noauth",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 10,
                    "payload_base64": _b64(payload),
                }
            ],
        },
    )
    assert response.status_code == 503


def test_aggregation_wrong_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    reference = _make_model_payload()
    response = client.post(
        ENDPOINT,
        headers={"Authorization": "Bearer wrong"},
        json={
            "model_version": "cnn-v1",
            "round_number": 1,
            "reference_payload_base64": _b64(reference),
            "updates": [
                {
                    "client_id": "c-001",
                    "update_id": "u-999",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 1,
                    "payload_base64": _b64(reference),
                }
            ],
        },
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

def test_aggregation_single_approved_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    reference = _make_model_payload(weight_val=1.0)
    payload = _register_and_approve(
        update_id="u-agg-single", payload=_make_model_payload(weight_val=0.5)
    )
    response = client.post(
        ENDPOINT,
        headers=AUTH_HEADERS,
        json={
            "model_version": "cnn-v1",
            "round_number": 1,
            "reference_payload_base64": _b64(reference),
            "updates": [
                {
                    "client_id": "c-001",
                    "update_id": "u-agg-single",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 10,
                    "payload_base64": _b64(payload),
                }
            ],
        },
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["model_version"] == "cnn-v1"
    assert body["round_number"] == 1
    assert body["update_count"] == 1
    assert body["total_samples"] == 10
    assert body["tensor_count"] == 2
    assert "aggregated_payload_base64" in body
    # Verify the aggregated payload can be decoded and deserialized.
    agg_bytes = base64.b64decode(body["aggregated_payload_base64"])
    assert len(agg_bytes) > 0


def test_aggregation_two_approved_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    reference = _make_model_payload(weight_val=1.0)
    payload_a = _register_and_approve(
        update_id="u-agg-two-a",
        client_id="c-001",
        payload=_make_model_payload(weight_val=0.0),
        sample_count=10,
    )
    payload_b = _register_and_approve(
        update_id="u-agg-two-b",
        client_id="c-002",
        payload=_make_model_payload(weight_val=1.0),
        sample_count=10,
    )
    response = client.post(
        ENDPOINT,
        headers=AUTH_HEADERS,
        json={
            "model_version": "cnn-v1",
            "round_number": 1,
            "reference_payload_base64": _b64(reference),
            "updates": [
                {
                    "client_id": "c-001",
                    "update_id": "u-agg-two-a",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 10,
                    "payload_base64": _b64(payload_a),
                },
                {
                    "client_id": "c-002",
                    "update_id": "u-agg-two-b",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 10,
                    "payload_base64": _b64(payload_b),
                },
            ],
        },
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["update_count"] == 2
    assert body["total_samples"] == 20


# ---------------------------------------------------------------------------
# Rejection cases
# ---------------------------------------------------------------------------

def test_unapproved_update_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    reference = _make_model_payload()
    payload = _make_model_payload(weight_val=0.5)
    # Register but do not approve.
    sha256 = hashlib.sha256(payload).hexdigest()
    register_validated_update(
        update_id="u-agg-unapproved",
        client_id="c-001",
        model_version="cnn-v1",
        round_number=1,
        sample_count_result=SampleCountResult(count=10, provenance=PROVENANCE_CLIENT_CLAIMED),
        payload_sha256=sha256,
        risk_score=0,
        risk_severity="LOW",
        suspicious=False,
        anomaly_reasons=(),
        detector_version="test-v1",
        detector_config={"max_weight_l2_norm": 100.0},
    )
    response = client.post(
        ENDPOINT,
        headers=AUTH_HEADERS,
        json={
            "model_version": "cnn-v1",
            "round_number": 1,
            "reference_payload_base64": _b64(reference),
            "updates": [
                {
                    "client_id": "c-001",
                    "update_id": "u-agg-unapproved",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 10,
                    "payload_base64": _b64(payload),
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "not approved" in response.json()["detail"].lower()


def test_wrong_model_version_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    reference = _make_model_payload()
    payload = _register_and_approve(
        update_id="u-agg-ver",
        payload=_make_model_payload(weight_val=0.5),
        model_version="cnn-v1",
    )
    response = client.post(
        ENDPOINT,
        headers=AUTH_HEADERS,
        json={
            "model_version": "cnn-v1",
            "round_number": 1,
            "reference_payload_base64": _b64(reference),
            "updates": [
                {
                    "client_id": "c-001",
                    "update_id": "u-agg-ver",
                    "model_version": "cnn-v2",  # mismatched version
                    "round_number": 1,
                    "sample_count": 10,
                    "payload_base64": _b64(payload),
                }
            ],
        },
    )
    assert response.status_code == 422


def test_invalid_reference_base64_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    response = client.post(
        ENDPOINT,
        headers=AUTH_HEADERS,
        json={
            "model_version": "cnn-v1",
            "round_number": 1,
            "reference_payload_base64": "%%%notbase64%%%",
            "updates": [
                {
                    "client_id": "c-001",
                    "update_id": "u-999",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 1,
                    "payload_base64": "AAAA",
                }
            ],
        },
    )
    assert response.status_code == 400


def test_modified_payload_digest_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Submitting a payload whose bytes differ from the approved digest is rejected."""
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    reference = _make_model_payload()
    original_payload = _make_model_payload(weight_val=0.5)
    _register_and_approve(update_id="u-agg-tamper", payload=original_payload)
    # Alter the last byte.
    tampered = original_payload[:-1] + bytes([original_payload[-1] ^ 0xFF])
    response = client.post(
        ENDPOINT,
        headers=AUTH_HEADERS,
        json={
            "model_version": "cnn-v1",
            "round_number": 1,
            "reference_payload_base64": _b64(reference),
            "updates": [
                {
                    "client_id": "c-001",
                    "update_id": "u-agg-tamper",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 10,
                    "payload_base64": _b64(tampered),
                }
            ],
        },
    )
    assert response.status_code == 422
