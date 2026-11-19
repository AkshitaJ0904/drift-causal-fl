
"""API tests for update integrity, cryptographic authentication, and detection."""

import base64
import hashlib
from collections.abc import Generator

import pytest
import torch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from api import ingestion
from app.main import app
from core.crypto import sign_envelope
from core.key_registry import clear_trusted_keys, register_trusted_key
from core.model_registry import clear_model_schemas, register_model_schema
from core.replay_protection import clear_replay_registry
from enforcement.approval_service import (
    UpdateStatus,
    clear_approval_registry,
    get_update_record,
)
from ingestion.schemas import UpdateEnvelope
from ingestion.serialization import serialize_state_dict

client = TestClient(app)
ENDPOINT = "/api/v1/updates"

# Test-only key pair. Never use a test private key in production.
TEST_PRIVATE_KEY = Ed25519PrivateKey.generate()
TEST_PUBLIC_KEY = TEST_PRIVATE_KEY.public_key()


def valid_model_payload(weight_val: float = 1.0) -> bytes:
    """Create a valid serialized model-weight payload."""
    return serialize_state_dict(
        {
            "layer.weight": torch.tensor([[weight_val, weight_val]], dtype=torch.float32),
            "layer.bias": torch.tensor([0.5], dtype=torch.float32),
        }
    )


@pytest.fixture(autouse=True)
def reset_security_registries() -> Generator[None, None, None]:
    """Reset in-memory security state around each API test."""
    clear_trusted_keys()
    clear_replay_registry()
    clear_approval_registry()
    clear_model_schemas()

    register_model_schema(
        model_version="cnn-v1",
        state_dict={
            "layer.weight": torch.zeros((1, 2), dtype=torch.float32),
            "layer.bias": torch.zeros(1, dtype=torch.float32),
        },
    )

    yield

    clear_trusted_keys()
    clear_replay_registry()
    clear_approval_registry()
    clear_model_schemas()


def make_request(
    payload: bytes,
    *,
    client_id: str = "client-001",
    update_id: str = "update-001",
    sample_count: int = 1,
) -> dict:
    """Build a signed request and register its test public key."""
    envelope = UpdateEnvelope.model_validate(
        {
            "update_id": update_id,
            "client_id": client_id,
            "model_version": "cnn-v1",
            "round_number": 1,
            "sample_count": sample_count,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
            "created_at": "2026-10-21T10:00:00Z",
            "signature": "temporary-placeholder",
            "signing_key_id": "key-001",
        }
    )

    signature = sign_envelope(envelope, TEST_PRIVATE_KEY)
    envelope = envelope.model_copy(update={"signature": signature})

    register_trusted_key(
        key_id="key-001",
        client_id=client_id,
        public_key=TEST_PUBLIC_KEY,
        max_sample_count=10_000,
    )

    return {
        "envelope": envelope.model_dump(mode="json"),
        "payload_base64": base64.b64encode(payload).decode("ascii"),
    }


def test_replayed_signed_update_is_rejected() -> None:
    request_data = make_request(valid_model_payload())

    first_response = client.post(ENDPOINT, json=request_data)
    second_response = client.post(ENDPOINT, json=request_data)

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == "Duplicate update detected"


def test_valid_signed_update_returns_success_and_requires_approval() -> None:
    payload = valid_model_payload()
    request_data = make_request(payload)

    response = client.post(ENDPOINT, json=request_data)

    assert response.status_code == 200

    body = response.json()
    assert body["update_id"] == "update-001"
    assert body["client_id"] == "client-001"
    assert body["payload_sha256"] == hashlib.sha256(payload).hexdigest()
    assert body["integrity_status"] == "verified"
    assert body["authentication_status"] == "verified"
    assert body["serialization_status"] == "verified"
    assert body["schema_status"] == "verified"
    assert body["policy_status"] == "accepted"
    assert body["ingestion_status"] == "validated"
    assert body["approval_status"] == UpdateStatus.PENDING_APPROVAL.value
    assert body["aggregation_status"] == "not_authorized"
    assert body["tensor_count"] == 2
    assert "state_dict" not in body
    assert "tensor_names" not in body
    assert "risk_score" in body
    assert "severity" in body
    assert "suspicious" in body
    assert body["suspicious"] is False

    record = get_update_record(
        client_id="client-001",
        update_id="update-001",
    )
    assert record is not None
    assert record.status == UpdateStatus.PENDING_APPROVAL


def test_suspicious_update_is_flagged_in_api_and_retains_pending_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Lower max_weight_l2_norm threshold via a detection_config injected at the service level.
    # We cannot rely on monkeypatch.setenv because get_detection_config calls get_settings()
    # which is @lru_cache -- the env var change would not propagate to the cached Settings.
    # Instead we monkeypatch get_detection_config in the ingestion service module directly.
    import ingestion.service as ingestion_service_mod
    from detection.rule_based import RuleBasedDetectionConfig

    def mock_get_detection_config(settings=None):
        return RuleBasedDetectionConfig(
            max_weight_l2_norm=0.5,
            max_update_l2_norm=None,
        )

    monkeypatch.setattr(ingestion_service_mod, "get_detection_config", mock_get_detection_config)

    payload = valid_model_payload(weight_val=2.0)
    request_data = make_request(payload, update_id="update-suspicious-api")

    response = client.post(ENDPOINT, json=request_data)

    assert response.status_code == 200
    body = response.json()
    assert body["suspicious"] is True
    assert body["risk_score"] > 0
    assert body["approval_status"] == UpdateStatus.PENDING_APPROVAL.value
    assert len(body["anomaly_reasons"]) >= 1

    record = get_update_record(
        client_id="client-001",
        update_id="update-suspicious-api",
    )
    assert record.status == UpdateStatus.PENDING_APPROVAL
    assert "human review required" in record.reason


def test_modified_payload_is_rejected() -> None:
    original_payload = valid_model_payload()
    modified_payload = original_payload[:-1] + bytes(
        [original_payload[-1] ^ 1]
    )

    request_data = make_request(original_payload)
    request_data["payload_base64"] = base64.b64encode(
        modified_payload
    ).decode("ascii")

    response = client.post(ENDPOINT, json=request_data)

    assert response.status_code == 422
    assert "digest" in response.json()["detail"].lower()


def test_invalid_base64_is_rejected() -> None:
    request_data = make_request(valid_model_payload())
    request_data["payload_base64"] = "%%%not-base64%%%"

    response = client.post(ENDPOINT, json=request_data)

    assert response.status_code == 400


def test_oversized_request_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingestion, "MAX_REQUEST_SIZE_BYTES", 10)

    response = client.post(
        ENDPOINT,
        json=make_request(valid_model_payload()),
    )

    assert response.status_code == 413




def test_invalid_signature_is_rejected() -> None:
    request_data = make_request(valid_model_payload())
    request_data["envelope"]["signature"] = (
        "bm90LWEtdmFsaWQtc2lnbmF0dXJl"
    )

    response = client.post(ENDPOINT, json=request_data)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid update signature"


def test_unknown_signing_key_is_rejected() -> None:
    request_data = make_request(valid_model_payload())
    clear_trusted_keys()

    response = client.post(ENDPOINT, json=request_data)

    assert response.status_code == 401
    assert response.json()["detail"] == "Unknown signing key"


def test_key_for_another_client_is_rejected() -> None:
    request_data = make_request(valid_model_payload())

    register_trusted_key(
        key_id="key-001",
        client_id="another-client",
        public_key=TEST_PUBLIC_KEY,
        max_sample_count=10_000,
    )

    response = client.post(ENDPOINT, json=request_data)

    assert response.status_code == 401
    assert "not authorized" in response.json()["detail"]


def test_sample_count_above_trusted_key_limit_is_rejected() -> None:
    request_data = make_request(valid_model_payload(), sample_count=10_001)

    response = client.post(ENDPOINT, json=request_data)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "sample_count_limit_exceeded"


def test_sample_count_requires_a_server_configured_key_limit() -> None:
    request_data = make_request(valid_model_payload())
    register_trusted_key(
        key_id="key-001",
        client_id="client-001",
        public_key=TEST_PUBLIC_KEY,
    )

    response = client.post(ENDPOINT, json=request_data)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "sample_count_limit_missing"


def test_audit_failure_reported_in_api_response(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import OperationalError
    def mock_audit(*args, **kwargs):
        raise OperationalError("audit error", params=None, orig=Exception())

    # Must patch the name as imported in ingestion.service, not the source module,
    # because ingestion/service.py uses `from audit.service import record_audit_event`.
    import ingestion.service as ingestion_service_mod
    monkeypatch.setattr(ingestion_service_mod, "record_audit_event", mock_audit)

    response = client.post(
        ENDPOINT,
        json=make_request(valid_model_payload(), update_id="update-audit-api-fail"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["audit_status"] == "failed"
    assert body["approval_status"] == UpdateStatus.PENDING_APPROVAL.value
