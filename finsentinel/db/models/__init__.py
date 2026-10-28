
"""Database models."""

from db.models.audit_event import AuditEvent
from db.models.update_approval import UpdateApproval

__all__ = [
    "AuditEvent",
    "UpdateApproval",
]
