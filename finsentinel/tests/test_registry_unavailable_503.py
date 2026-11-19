"""Regression tests: registry DB unavailability must return HTTP 503, not 500.

Covers both confirmed defects:
  Defect 1 (key_registry): corrupted PEM → RegistryUnavailableError → 503
  Defect 2 (api/ingestion.py): RegistryUnavailableError not caught → was 500, now 503
"""

import base64
import hashlib

import pytest
import torch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.main import app
from core.crypto import sign_envelope
from core.key_registry import (
    RegistryUnavailableError as KeyRegistryUnavailableError,
)
from core.key_registry import (
    clear_trusted_keys,
    register_trusted_key,
)
from core.model_registry import (
    RegistryUnavailableError as ModelRegistryUnavailableError,
)
from core.model_registry import (
    clear_model_schemas,
    register_model_schema,
)
from core.replay_protection import clear_replay_registry
from enforcement.approval_service import clear_approval_registry
from ingestion.schemas import UpdateEnvelope
from ingestion.serialization import serialize_state_dict

client = TestClient(app)
ENDPOINT = "/api/v1/updates"

_PRIV = Ed25519PrivateKey.generate()
_PUB = _PRIV.public_key()


def _valid_payload() -> bytes:
    return serialize_state_dict(
        {
            "layer.weight": torch.tensor([[1.0, 1.0]], dtype=torch.float32),
            "layer.bias": torch.tensor([0.5], dtype=torch.float32),
        }
    )


@pytest.fixture(autouse=True)
def _reset():
    clear_trusted_keys()
    clear_replay_registry()
    clear_approval_registry()
    clear_model_schemas()
    register_model_schema(
        "cnn-v1",
        {
            "layer.weight": torch.zeros((1, 2), dtype=torch.float32),
            "layer.bias": torch.zeros(1, dtype=torch.float32),
        },
    )
    register_trusted_key("reg-key-001", "client-001", _PUB, max_sample_count=10_000)
    yield
    clear_trusted_keys()
    clear_replay_registry()
    clear_approval_registry()
    clear_model_schemas()


def _make_submission(*, update_id: str = "upd-503-001") -> dict:
    payload = _valid_payload()
    envelope = UpdateEnvelope.model_validate(
        {
            "update_id": update_id,
            "client_id": "client-001",
            "model_version": "cnn-v1",
            "round_number": 1,
            "sample_count": 1,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
            "created_at": "2026-10-21T10:00:00Z",
            "signature": "temporary-placeholder",
            "signing_key_id": "reg-key-001",
        }
    )
    signature = sign_envelope(envelope, _PRIV)
    envelope = envelope.model_copy(update={"signature": signature})
    return {
        "envelope": envelope.model_dump(mode="json"),
        "payload_base64": base64.b64encode(payload).decode("ascii"),
    }


# ---------------------------------------------------------------------------
# Key registry unavailable → 503
# ---------------------------------------------------------------------------


def test_key_registry_unavailable_returns_503(monkeypatch) -> None:
    """DB outage during key lookup must yield HTTP 503, not 500."""

    def _raise(_key_id: str):
        raise KeyRegistryUnavailableError("simulated key registry DB failure")

    monkeypatch.setattr("ingestion.service.get_trusted_key", _raise)

    response = client.post(ENDPOINT, json=_make_submission())
    assert response.status_code == 503, response.text


# ---------------------------------------------------------------------------
# Schema registry unavailable → 503
# ---------------------------------------------------------------------------


def test_schema_registry_unavailable_returns_503(monkeypatch) -> None:
    """DB outage during schema lookup must yield HTTP 503, not 500."""

    def _raise(_version: str):
        raise ModelRegistryUnavailableError("simulated schema registry DB failure")

    monkeypatch.setattr("core.model_registry.get_model_schema", _raise)

    response = client.post(ENDPOINT, json=_make_submission(update_id="upd-503-002"))
    assert response.status_code == 503, response.text
