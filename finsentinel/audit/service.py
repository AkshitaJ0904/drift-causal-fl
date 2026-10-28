"""Application service for recording security audit events."""

import logging

from sqlalchemy.exc import SQLAlchemyError

from core.supabase.session import SessionLocal
from db.models import AuditEvent

logger = logging.getLogger(__name__)


def record_audit_event(
    *,
    event_type: str,
    severity: str,
    description: str,
    client_id: str | None = None,
    update_id: str | None = None,
) -> int:
    """Persist a security audit event and return its database ID."""
    event = AuditEvent(
        event_type=event_type,
        severity=severity,
        description=description,
        client_id=client_id,
        update_id=update_id,
    )

    try:
        with SessionLocal() as db:
            db.add(event)
            db.commit()
            db.refresh(event)
            return event.id
    except SQLAlchemyError:
        logger.exception(
            "Failed to persist audit event: event_type=%s",
            event_type,
        )
        raise