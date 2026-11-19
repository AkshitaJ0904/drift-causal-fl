"""Application service for recording security audit events."""

import logging

from sqlalchemy.exc import SQLAlchemyError

from audit.outbox import enqueue
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
    """Persist a security audit event and stage it for outbox delivery.

    Both the ``AuditEvent`` row and the corresponding ``AuditOutboxRecord``
    are written in a single transaction so neither is lost if the process
    crashes between them.

    Returns the database ID of the new ``AuditEvent``.
    """
    event = AuditEvent(
        event_type=event_type,
        severity=severity,
        description=description,
        client_id=client_id,
        update_id=update_id,
    )

    try:
        with SessionLocal() as db:
            with db.begin():
                db.add(event)
                db.flush()  # populate event.id before enqueueing
                enqueue(
                    db,
                    event_id=event.id,
                    event_type=event_type,
                    severity=severity,
                    description=description,
                    client_id=client_id,
                    update_id=update_id,
                )
        return event.id
    except SQLAlchemyError:
        logger.exception(
            "Failed to persist audit event: event_type=%s",
            event_type,
        )
        raise
