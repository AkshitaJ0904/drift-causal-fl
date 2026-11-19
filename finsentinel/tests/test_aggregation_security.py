
"""Security-focused negative tests for the aggregation API.

Covers validation of the integer-tensor server-reference fix (B1),
duplicate update detection, round-number mismatch, and empty-update
rejection.  Positive-path and auth coverage lives in test_aggregation_api.py.
"""

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

TEST_TOKEN = "test-aggregation-security-token"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture(autouse=True)
def reset_registry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", TEST_TOKEN)
    clear_approval_registry()
    yield
    clear_approval_registry()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _make_float_model(weight_val: float = 1.0) -> bytes:
    return serialize_state_dict(
        {
            "layer.weight": torch.tensor([[weight_val]], dtype=torch.float32),
            "layer.bias": torch.tensor([0.0], dtype=torch.float32),
        }
    )


def _make_mixed_model(weight_val: float = 1.0, counter: int = 0) -> bytes:
    """Model with both float and integer tensors."""
    return serialize_state_dict(
        {
            "layer.weight": torch.tensor([[weight_val]], dtype=torch.float32),
            "counter": torch.tensor([counter], dtype=torch.int64),
        }
    )


def _register_and_approve(
    *,
    update_id: str,
    client_id: str = "c-001",
    model_version: str = "cnn-v1",
    round_number: int = 1,
    sample_count: int = 10,
    payload: bytes,
) -> bytes:
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
        reason="Approved for aggregation security test.",
    )
    return payload


# ---------------------------------------------------------------------------
# Empty updates (Pydantic validation at HTTP layer)
# ---------------------------------------------------------------------------

def test_empty_updates_list_returns_422() -> None:
    """The updates list must have at least one element (Pydantic min_length=1)."""
    reference = _make_float_model()
    response = client.post(
        ENDPOINT,
        headers=AUTH_HEADERS,
        json={
            "model_version": "cnn-v1",
            "round_number": 1,
            "reference_payload_base64": _b64(reference),
            "updates": [],
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Duplicate update_id in the same aggregation request
# ---------------------------------------------------------------------------

def test_duplicate_update_id_in_request_returns_422() -> None:
    """Two entries in the same request with identical (client_id, update_id) → 422."""
    reference = _make_float_model()
    payload = _register_and_approve(
        update_id="u-dup",
        payload=_make_float_model(weight_val=0.5),
    )
    update_entry = {
        "client_id": "c-001",
        "update_id": "u-dup",
        "model_version": "cnn-v1",
        "round_number": 1,
        "sample_count": 10,
        "payload_base64": _b64(payload),
    }
    response = client.post(
        ENDPOINT,
        headers=AUTH_HEADERS,
        json={
            "model_version": "cnn-v1",
            "round_number": 1,
            "reference_payload_base64": _b64(reference),
            "updates": [update_entry, update_entry],
        },
    )
    assert response.status_code == 422
    assert "duplicate" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Per-update round_number mismatch against top-level round_number
# ---------------------------------------------------------------------------

def test_round_number_mismatch_per_update_returns_422() -> None:
    """An update whose round_number differs from the request round_number → 422."""
    reference = _make_float_model()
    payload = _register_and_approve(
        update_id="u-round-mismatch",
        round_number=1,
        payload=_make_float_model(weight_val=0.5),
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
                    "update_id": "u-round-mismatch",
                    "model_version": "cnn-v1",
                    "round_number": 2,  # intentional mismatch
                    "sample_count": 10,
                    "payload_base64": _b64(payload),
                }
            ],
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Integer tensor: client differs from server reference (B1 fix verification)
# ---------------------------------------------------------------------------

def test_integer_tensor_matching_server_reference_succeeds() -> None:
    """When client integer tensor matches server reference, aggregation succeeds."""
    server_counter = 0
    reference = _make_mixed_model(weight_val=1.0, counter=server_counter)
    # Client sends the same counter value as the server reference.
    client_payload = _register_and_approve(
        update_id="u-int-match",
        payload=_make_mixed_model(weight_val=0.5, counter=server_counter),
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
                    "update_id": "u-int-match",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 10,
                    "payload_base64": _b64(client_payload),
                }
            ],
        },
    )
    assert response.status_code == 200, response.json()


def test_integer_tensor_differing_from_server_reference_is_rejected() -> None:
    """Client integer tensor that differs from server reference → 422.

    Without the B1 fix, a single client comparing only against itself would
    pass (trivially equal).  The fix requires all clients to match the
    server's trusted reference value, preventing coordinated override attacks.
    """
    server_counter = 0
    client_counter = 99  # Differs from server
    reference = _make_mixed_model(weight_val=1.0, counter=server_counter)
    client_payload = _register_and_approve(
        update_id="u-int-mismatch",
        payload=_make_mixed_model(weight_val=0.5, counter=client_counter),
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
                    "update_id": "u-int-mismatch",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 10,
                    "payload_base64": _b64(client_payload),
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "server reference" in response.json()["detail"]


def test_two_clients_agreeing_on_wrong_integer_tensor_are_rejected() -> None:
    """Two clients with the same wrong integer value are still rejected.

    Old code only compared clients to each other; both agreeing on a forged
    value would pass.  The new code requires all clients to match the server.
    """
    server_counter = 0
    forged_counter = 42  # Both clients agree, but it differs from server
    reference = _make_mixed_model(weight_val=1.0, counter=server_counter)
    payload_a = _register_and_approve(
        update_id="u-agree-a",
        client_id="c-001",
        payload=_make_mixed_model(weight_val=0.5, counter=forged_counter),
    )
    payload_b = _register_and_approve(
        update_id="u-agree-b",
        client_id="c-002",
        payload=_make_mixed_model(weight_val=0.8, counter=forged_counter),
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
                    "update_id": "u-agree-a",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 10,
                    "payload_base64": _b64(payload_a),
                },
                {
                    "client_id": "c-002",
                    "update_id": "u-agree-b",
                    "model_version": "cnn-v1",
                    "round_number": 1,
                    "sample_count": 10,
                    "payload_base64": _b64(payload_b),
                },
            ],
        },
    )
    assert response.status_code == 422
    assert "server reference" in response.json()["detail"]
