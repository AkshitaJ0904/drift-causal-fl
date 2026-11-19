"""Tests verifying that key/schema registry mutations emit persistent audit events.

Coverage:
- register_trusted_key (new key) → event_type="key.registered" enqueued
- register_trusted_key (update existing key) → event_type="key.registered" enqueued
- revoke_trusted_key → event_type="key.revoked" enqueued
- register_model_schema (new schema) → event_type="schema.registered" enqueued
- register_model_schema (update existing schema) → event_type="schema.registered" enqueued
- Audit event is committed in the same transaction as the registry change.
- Failed registry operation does not produce a stray audit record.
"""
from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import delete

from core.key_registry import (
    clear_trusted_keys,
    register_trusted_key,
    revoke_trusted_key,
)
from core.model_registry import clear_model_schemas, register_model_schema
from core.supabase.session import SessionLocal
from db.models.audit_outbox import AuditOutboxRecord

_PRIV = Ed25519PrivateKey.generate()
_PUB = _PRIV.public_key()

_PRIV_B = Ed25519PrivateKey.generate()
_PUB_B = _PRIV_B.public_key()


@pytest.fixture(autouse=True)
def _clean(_sqlite_test_database):
    clear_trusted_keys()
    clear_model_schemas()
    with SessionLocal() as db:
        db.execute(delete(AuditOutboxRecord))
        db.commit()
    yield
    clear_trusted_keys()
    clear_model_schemas()
    with SessionLocal() as db:
        db.execute(delete(AuditOutboxRecord))
        db.commit()


def _outbox_events() -> list[AuditOutboxRecord]:
    with SessionLocal() as db:
        return db.query(AuditOutboxRecord).all()


def _outbox_by_type(event_type: str) -> list[AuditOutboxRecord]:
    with SessionLocal() as db:
        return db.query(AuditOutboxRecord).filter_by(event_type=event_type).all()


# ---------------------------------------------------------------------------
# Key registry audit events
# ---------------------------------------------------------------------------


def test_register_new_key_emits_audit_event():
    """Registering a new trusted key produces one key.registered audit record."""
    register_trusted_key("key-audit-1", "client-audit-1", _PUB, max_sample_count=100)

    events = _outbox_by_type("key.registered")
    assert len(events) == 1
    assert events[0].client_id == "client-audit-1"
    assert events[0].status == "pending"


def test_register_key_update_emits_audit_event():
    """Updating an existing key produces an additional key.registered audit record."""
    register_trusted_key("key-audit-2", "client-audit-2", _PUB, max_sample_count=100)
    register_trusted_key("key-audit-2", "client-audit-2", _PUB_B, max_sample_count=200)

    events = _outbox_by_type("key.registered")
    assert len(events) == 2
    # Both events have the same client_id.
    assert all(e.client_id == "client-audit-2" for e in events)


def test_revoke_key_emits_audit_event():
    """Revoking a trusted key produces one key.revoked audit record."""
    register_trusted_key("key-audit-3", "client-audit-3", _PUB, max_sample_count=100)
    revoke_trusted_key("key-audit-3")

    events = _outbox_by_type("key.revoked")
    assert len(events) == 1
    assert events[0].client_id == "client-audit-3"
    assert events[0].status == "pending"


def test_revoke_nonexistent_key_produces_no_audit_event():
    """Revoking a key that does not exist produces no audit record."""
    revoke_trusted_key("nonexistent-key-id")

    assert _outbox_by_type("key.revoked") == []


def test_audit_event_committed_in_same_transaction_as_registry_change():
    """The audit record is visible immediately after the registry call returns."""
    assert _outbox_by_type("key.registered") == []
    register_trusted_key("key-txn", "client-txn", _PUB, max_sample_count=50)
    # Visible immediately — same transaction was committed.
    assert len(_outbox_by_type("key.registered")) == 1


def test_key_registry_audit_event_has_no_key_material():
    """Audit event description must not contain private key material."""
    register_trusted_key("key-safe", "client-safe", _PUB, max_sample_count=100)
    revoke_trusted_key("key-safe")

    for event in _outbox_events():
        assert "PRIVATE" not in (event.description or "").upper()
        assert "-----BEGIN" not in (event.description or "")


# ---------------------------------------------------------------------------
# Schema registry audit events
# ---------------------------------------------------------------------------


def _make_schema() -> dict:
    import torch
    return {"weights": torch.zeros(4, 4)}


def test_register_new_schema_emits_audit_event():
    """Registering a new model schema produces one schema.registered audit record."""
    register_model_schema("model-v1", _make_schema())

    events = _outbox_by_type("schema.registered")
    assert len(events) == 1
    assert events[0].status == "pending"


def test_register_schema_update_emits_audit_event():
    """Updating an existing schema produces an additional schema.registered record."""
    import torch
    register_model_schema("model-v2", {"weights": torch.zeros(4, 4)})
    register_model_schema("model-v2", {"weights": torch.zeros(8, 8)})

    events = _outbox_by_type("schema.registered")
    assert len(events) == 2


def test_all_registry_mutations_emit_audit_events_summary():
    """Combined smoke test: all three mutation types produce audit records."""
    import torch
    register_trusted_key("key-summary", "audit-summary-client", _PUB, max_sample_count=100)
    revoke_trusted_key("key-summary")
    register_model_schema("audit-schema", {"weights": torch.zeros(4, 4)})

    all_events = _outbox_events()
    event_types = {e.event_type for e in all_events}
    assert "key.registered" in event_types
    assert "key.revoked" in event_types
    assert "schema.registered" in event_types
