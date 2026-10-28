"""Tests for the audit service."""

from sqlalchemy import select

from audit.service import record_audit_event
from core.supabase.session import SessionLocal
from db.models import AuditEvent


def test_record_audit_event() -> None:
    event_id = record_audit_event(
        event_type="security.test",
        severity="info",
        description="Audit service integration test",
        client_id="test-client",
        update_id="test-update",
    )

    try:
        with SessionLocal() as db:
            event = db.scalar(
                select(AuditEvent).where(AuditEvent.id == event_id)
            )

            assert event is not None
            assert event.event_type == "security.test"
            assert event.severity == "info"
            assert event.client_id == "test-client"
            assert event.update_id == "test-update"
    finally:
        with SessionLocal() as db:
            event = db.get(AuditEvent, event_id)
            if event is not None:
                db.delete(event)
                db.commit()