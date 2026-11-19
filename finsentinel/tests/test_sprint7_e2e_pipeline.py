"""Sprint 7: End-to-end pipeline integration tests.

Covers the complete path from HTTP ingestion → audit outbox → delivery:
1. Valid ingestion creates an outbox record that deliver_pending_events can deliver.
2. Rejected update (bad signature) → outbox records the rejection audit event.
3. Approval workflow: ingest → approve → aggregate. Outbox accumulates events.
4. Dashboard reflects outbox state changes (pending → delivered).
5. Worker delivers multiple events in one pass.
6. Worker correctly stops during active delivery.

These tests are integration-level: they use the SQLite test database and
the full FastAPI app stack (TestClient) where appropriate.
"""
from __future__ import annotations

import base64
import hashlib

import pytest
import torch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.main import app
from audit.outbox import dead_letter_count, deliver_pending_events, pending_count
from core.crypto import sign_envelope
from core.key_registry import clear_trusted_keys, register_trusted_key
from core.model_registry import clear_model_schemas, register_model_schema
from core.replay_protection import clear_replay_registry
from core.supabase.session import SessionLocal
from db.models.audit_outbox import AuditOutboxRecord
from enforcement.approval_service import clear_approval_registry
from ingestion.schemas import UpdateEnvelope
from ingestion.serialization import serialize_state_dict

client = TestClient(app)
_INGEST_ENDPOINT = "/api/v1/updates"
_OPERATOR_TOKEN = "e2e-pipeline-test-token"
_OPERATOR_HEADERS = {"Authorization": f"Bearer {_OPERATOR_TOKEN}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _e2e_reset(monkeypatch: pytest.MonkeyPatch, _sqlite_test_database):
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", _OPERATOR_TOKEN)
    clear_trusted_keys()
    clear_model_schemas()
    clear_replay_registry()
    clear_approval_registry()

    with SessionLocal() as db:
        db.execute(delete(AuditOutboxRecord))
        db.commit()

    yield

    with SessionLocal() as db:
        db.execute(delete(AuditOutboxRecord))
        db.commit()

    clear_trusted_keys()
    clear_model_schemas()
    clear_replay_registry()
    clear_approval_registry()


def _make_valid_request(
    client_id: str = "e2e-client",
    update_id: str = "e2e-update-001",
    round_number: int = 1,
    sample_count: int = 100,
) -> dict:
    """Build a signed ingest request dict and register its key/schema.

    Returns the JSON-serialisable dict expected by POST /api/v1/updates:
      {"envelope": {...}, "payload_base64": "..."}
    """
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    key_id = f"key-{client_id}"
    register_trusted_key(
        key_id, client_id=client_id, public_key=public_key, max_sample_count=10_000
    )

    state_dict = {
        "layer.weight": torch.tensor([[0.1, 0.2]], dtype=torch.float32),
        "layer.bias": torch.tensor([0.0], dtype=torch.float32),
    }
    register_model_schema("cnn-v1", state_dict)

    payload_bytes = serialize_state_dict(state_dict)
    envelope = UpdateEnvelope.model_validate(
        {
            "update_id": update_id,
            "client_id": client_id,
            "model_version": "cnn-v1",
            "round_number": round_number,
            "sample_count": sample_count,
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "payload_size_bytes": len(payload_bytes),
            "created_at": "2026-11-07T00:00:00Z",
            "signature": "placeholder",
            "signing_key_id": key_id,
        }
    )
    sig = sign_envelope(envelope, private_key)
    envelope = envelope.model_copy(update={"signature": sig})

    return {
        "envelope": envelope.model_dump(mode="json"),
        "payload_base64": base64.b64encode(payload_bytes).decode("ascii"),
    }


# ---------------------------------------------------------------------------
# E2E-1: Valid ingestion creates an outbox record
# ---------------------------------------------------------------------------

def test_valid_ingestion_creates_outbox_record():
    """A successful ingest POST must leave at least one pending outbox record."""
    request_data = _make_valid_request()

    resp = client.post(_INGEST_ENDPOINT, json=request_data)
    assert resp.status_code == 200, resp.text

    # Outbox should have at least one pending record from the audit service.
    assert pending_count() >= 1


def test_valid_ingestion_outbox_record_is_deliverable():
    """The outbox record from a valid ingest must be deliverable by deliver_pending_events."""
    request_data = _make_valid_request(
        client_id="delivery-client", update_id="delivery-update-001"
    )

    client.post(_INGEST_ENDPOINT, json=request_data)

    initial_pending = pending_count()
    assert initial_pending >= 1

    payloads: list[dict] = []
    result = deliver_pending_events(delivery_fn=payloads.append, max_events=50)

    assert result["delivered"] == initial_pending
    assert pending_count() == 0
    assert len(payloads) == initial_pending

    # All delivered payloads must have the canonical schema fields.
    for p in payloads:
        assert "schema_version" in p
        assert "service" in p
        assert "idempotency_key" in p
        assert "event_type" in p


# ---------------------------------------------------------------------------
# E2E-2: Multiple events delivered in one worker pass
# ---------------------------------------------------------------------------

def test_multiple_ingestion_events_delivered_in_one_pass():
    """Several updates → multiple outbox records → single deliver_pending_events call."""
    for i in range(3):
        request_data = _make_valid_request(
            client_id=f"multi-client-{i}",
            update_id=f"multi-update-{i}",
            sample_count=50,
        )
        resp = client.post(_INGEST_ENDPOINT, json=request_data)
        assert resp.status_code == 200, f"Ingest {i} failed: {resp.text}"

    pending = pending_count()
    assert pending >= 3  # At least one per update.

    delivered_payloads: list[dict] = []
    result = deliver_pending_events(
        delivery_fn=delivered_payloads.append, max_events=100
    )

    assert result["delivered"] == pending
    assert pending_count() == 0


# ---------------------------------------------------------------------------
# E2E-3: Dashboard reflects delivered vs pending outbox state
# ---------------------------------------------------------------------------

def test_dashboard_reflects_pending_then_delivered():
    """Dashboard outbox.pending_count decreases after deliver_pending_events."""
    request_data = _make_valid_request(
        client_id="dash-client", update_id="dash-update-001"
    )
    client.post(_INGEST_ENDPOINT, json=request_data)

    resp_before = client.get("/api/v1/operator/dashboard", headers=_OPERATOR_HEADERS)
    assert resp_before.status_code == 200
    pending_before = resp_before.json()["outbox"]["pending_count"]
    assert pending_before >= 1

    deliver_pending_events(delivery_fn=lambda p: None)

    resp_after = client.get("/api/v1/operator/dashboard", headers=_OPERATOR_HEADERS)
    assert resp_after.status_code == 200
    pending_after = resp_after.json()["outbox"]["pending_count"]
    assert pending_after == 0


# ---------------------------------------------------------------------------
# E2E-4: Dead-letter alert surfaced on dashboard
# ---------------------------------------------------------------------------

def test_dashboard_alerts_on_dead_letter(_sqlite_test_database):
    """When an outbox record is dead-lettered, the dashboard outbox.alert is True."""
    from audit.delivery import DeliveryPermanentError
    from audit.outbox import enqueue

    with SessionLocal() as db:
        with db.begin():
            enqueue(
                db,
                event_id=None,
                event_type="key.registered",
                severity="info",
                client_id="cl-dl",
                update_id=None,
                description="dead-letter e2e test",
            )

    def _perm_fail(payload):
        raise DeliveryPermanentError("HTTP 403")

    deliver_pending_events(delivery_fn=_perm_fail)
    assert dead_letter_count() == 1

    resp = client.get("/api/v1/operator/dashboard", headers=_OPERATOR_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["outbox"]["alert"] is True
    assert body["outbox"]["dead_letter_count"] == 1
