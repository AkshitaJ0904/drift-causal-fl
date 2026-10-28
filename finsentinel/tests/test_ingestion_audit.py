
"""Integration tests for automatic ingestion security auditing."""

from uuid import uuid4

import pytest
import torch
from sqlalchemy import select

from api import ingestion
from core.crypto import sign_envelope
from core.key_registry import clear_trusted_keys
from core.model_registry import clear_model_schemas, register_model_schema
from core.replay_protection import clear_replay_registry
from core.supabase.session import SessionLocal
from db.models import AuditEvent
from enforcement.approval_service import clear_approval_registry
from ingestion.schemas import UpdateEnvelope
from ingestion.serialization import serialize_state_dict
from tests.test_ingestion_api import (
    ENDPOINT,
    TEST_PRIVATE_KEY,
    client,
    make_request,
)


def find_audit_event(
    *,
    event_type: str,
    client_id: str,
    update_id: str,
) -> AuditEvent | None:
    """Find a specific audit event in Supabase."""
    with SessionLocal() as db:
        return db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.event_type == event_type,
                AuditEvent.client_id == client_id,
                AuditEvent.update_id == update_id,
            )
            .order_by(AuditEvent.id.desc())
        )


def cleanup_audit_events(*, client_id: str, update_id: str) -> None:
    """Delete audit records created by an integration test."""
    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.client_id == client_id,
                AuditEvent.update_id == update_id,
            )
        ).all()

        for event in events:
            db.delete(event)

        db.commit()


@pytest.fixture(autouse=True)
def reset_security_registries():
    """Reset in-memory security state around each audit test."""
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


def test_invalid_signature_is_audited() -> None:
    payload = serialize_state_dict(
        {
            "layer.weight": torch.tensor([[1.0, 2.0]]),
            "layer.bias": torch.tensor([0.5]),
        }
    )
    request_data = make_request(payload)

    unique_id = uuid4().hex
    request_data["envelope"]["update_id"] = f"invalid-{unique_id}"

    # Changing the update ID invalidates the original signature.
    response = client.post(ENDPOINT, json=request_data)

    client_id = request_data["envelope"]["client_id"]
    update_id = request_data["envelope"]["update_id"]

    try:
        assert response.status_code == 401

        event = find_audit_event(
            event_type="security.signature_verification_failed",
            client_id=client_id,
            update_id=update_id,
        )
        assert event is not None
        assert event.severity == "high"
    finally:
        cleanup_audit_events(
            client_id=client_id,
            update_id=update_id,
        )


def test_replayed_update_is_audited() -> None:
    payload = serialize_state_dict(
        {
            "layer.weight": torch.tensor([[1.0, 2.0]]),
            "layer.bias": torch.tensor([0.5]),
        }
    )

    unique_id = uuid4().hex
    request_data = make_request(
        payload,
        update_id=f"replay-{unique_id}",
    )

    # Re-sign the envelope so the test uses a valid signature.
    envelope = UpdateEnvelope.model_validate(request_data["envelope"])
    signature = sign_envelope(envelope, TEST_PRIVATE_KEY)
    envelope = envelope.model_copy(update={"signature": signature})
    request_data["envelope"] = envelope.model_dump(mode="json")

    client_id = envelope.client_id
    update_id = envelope.update_id

    try:
        first_response = client.post(ENDPOINT, json=request_data)
        second_response = client.post(ENDPOINT, json=request_data)

        assert first_response.status_code == 200
        assert second_response.status_code == 409

        event = find_audit_event(
            event_type="security.replay_detected",
            client_id=client_id,
            update_id=update_id,
        )
        assert event is not None
        assert event.severity == "high"
    finally:
        cleanup_audit_events(
            client_id=client_id,
            update_id=update_id,
        )


def test_successful_ingestion_audits_pending_approval() -> None:
    unique_id = uuid4().hex
    update_id = f"approval-{unique_id}"
    client_id = f"client-{unique_id}"

    payload = serialize_state_dict(
        {
            "layer.weight": torch.tensor([[1.0, 2.0]]),
            "layer.bias": torch.tensor([0.5]),
        }
    )
    request_data = make_request(
        payload,
        client_id=client_id,
        update_id=update_id,
    )

    try:
        response = client.post(ENDPOINT, json=request_data)
        assert response.status_code == 200
        assert response.json()["approval_status"] == "pending_approval"
        assert response.json()["aggregation_status"] == "not_authorized"

        authenticated_event = find_audit_event(
            event_type="security.update_authenticated",
            client_id=client_id,
            update_id=update_id,
        )
        assert authenticated_event is not None

        pending_event = find_audit_event(
            event_type="security.update_pending_approval",
            client_id=client_id,
            update_id=update_id,
        )
        assert pending_event is not None
        assert pending_event.severity == "info"
    finally:
        cleanup_audit_events(
            client_id=client_id,
            update_id=update_id,
        )
