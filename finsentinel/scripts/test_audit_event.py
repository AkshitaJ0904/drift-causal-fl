
"""Verify that FinSentinel can write and read audit events."""

from sqlalchemy import select

from core.supabase.session import SessionLocal
from db.models import AuditEvent


def main() -> None:
    with SessionLocal() as db:
        event = AuditEvent(
            event_type="system.test",
            severity="info",
            client_id="test-client",
            description="FinSentinel database audit test",
        )

        db.add(event)
        db.commit()
        db.refresh(event)

        print(f"Audit event inserted: ID={event.id}")

        saved_event = db.scalar(
            select(AuditEvent).where(AuditEvent.id == event.id)
        )

        if saved_event is None:
            raise RuntimeError("Audit event could not be retrieved.")

        print(f"Event type: {saved_event.event_type}")
        print(f"Created at: {saved_event.created_at}")

        # Remove the test record so it does not pollute the audit trail.
        db.delete(saved_event)
        db.commit()

        print("Database insert, read, and cleanup successful.")


if __name__ == "__main__":
    main()
