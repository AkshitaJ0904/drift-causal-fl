
"""Database-backed approval lifecycle for federated-learning updates."""

from dataclasses import dataclass
from enum import Enum
import re

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from core.supabase.session import SessionLocal
from db.models.update_approval import UpdateApproval


_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateStatus(str, Enum):
    VALIDATED = "validated"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class ApprovalError(ValueError):
    """Raised when an update lifecycle operation is invalid."""


@dataclass(frozen=True)
class UpdateRecord:
    update_id: str
    client_id: str
    model_version: str
    round_number: int
    payload_sha256: str
    status: UpdateStatus
    reason: str


def _to_record(row: UpdateApproval) -> UpdateRecord:
    return UpdateRecord(
        update_id=row.update_id,
        client_id=row.client_id,
        model_version=row.model_version,
        round_number=row.round_number,
        payload_sha256=row.payload_sha256,
        status=UpdateStatus(row.status),
        reason=row.reason,
    )


def register_validated_update(
    *,
    update_id: str,
    client_id: str,
    model_version: str,
    round_number: int,
    payload_sha256: str,
) -> UpdateRecord:
    """Register a validated payload as pending approval."""
    if not all(
        value.strip()
        for value in (update_id, client_id, model_version)
    ):
        raise ValueError(
            "Update, client, and model identifiers are required."
        )

    if round_number < 1:
        raise ValueError("round_number must be positive.")

    if not _SHA256_PATTERN.fullmatch(payload_sha256):
        raise ValueError("A valid SHA-256 payload digest is required.")

    row = UpdateApproval(
        update_id=update_id,
        client_id=client_id,
        model_version=model_version,
        round_number=round_number,
        payload_sha256=payload_sha256.lower(),
        status=UpdateStatus.PENDING_APPROVAL.value,
        reason="Security validation passed; approval is still required.",
    )

    try:
        with SessionLocal() as db:
            with db.begin():
                db.add(row)
                db.flush()
            return _to_record(row)
    except IntegrityError as exc:
        raise ApprovalError("Update is already registered.") from exc


def _transition(
    *,
    client_id: str,
    update_id: str,
    new_status: UpdateStatus,
    reason: str,
) -> UpdateRecord:
    """Atomically transition a pending update to a decision state."""
    if not reason.strip():
        raise ValueError("A non-empty decision reason is required.")

    if new_status not in {
        UpdateStatus.APPROVED,
        UpdateStatus.REJECTED,
        UpdateStatus.QUARANTINED,
    }:
        raise ValueError("Invalid target approval status.")

    with SessionLocal() as db:
        with db.begin():
            result = db.execute(
                update(UpdateApproval)
                .where(
                    UpdateApproval.client_id == client_id,
                    UpdateApproval.update_id == update_id,
                    UpdateApproval.status
                    == UpdateStatus.PENDING_APPROVAL.value,
                )
                .values(
                    status=new_status.value,
                    reason=reason.strip(),
                    updated_at=func.now(),
                    decided_at=func.now(),
                )
            )

            if result.rowcount != 1:
                existing = db.scalar(
                    select(UpdateApproval).where(
                        UpdateApproval.client_id == client_id,
                        UpdateApproval.update_id == update_id,
                    )
                )
                if existing is None:
                    raise ApprovalError("Unknown update.")
                raise ApprovalError(
                    f"Cannot transition update from {existing.status}."
                )

            row = db.scalar(
                select(UpdateApproval).where(
                    UpdateApproval.client_id == client_id,
                    UpdateApproval.update_id == update_id,
                )
            )
            if row is None:
                raise ApprovalError(
                    "Update disappeared during its state transition."
                )

            record = _to_record(row)

    return record


def approve_update(
    *,
    client_id: str,
    update_id: str,
    reason: str,
) -> UpdateRecord:
    """Approve a pending update for the enforcement stage."""
    return _transition(
        client_id=client_id,
        update_id=update_id,
        new_status=UpdateStatus.APPROVED,
        reason=reason,
    )


def reject_update(
    *,
    client_id: str,
    update_id: str,
    reason: str,
) -> UpdateRecord:
    """Reject a pending update."""
    return _transition(
        client_id=client_id,
        update_id=update_id,
        new_status=UpdateStatus.REJECTED,
        reason=reason,
    )


def quarantine_update(
    *,
    client_id: str,
    update_id: str,
    reason: str,
) -> UpdateRecord:
    """Quarantine a pending update for investigation."""
    return _transition(
        client_id=client_id,
        update_id=update_id,
        new_status=UpdateStatus.QUARANTINED,
        reason=reason,
    )


def get_update_record(
    *,
    client_id: str,
    update_id: str,
) -> UpdateRecord:
    """Retrieve a persisted lifecycle record."""
    with SessionLocal() as db:
        row = db.scalar(
            select(UpdateApproval).where(
                UpdateApproval.client_id == client_id,
                UpdateApproval.update_id == update_id,
            )
        )
        if row is None:
            raise ApprovalError("Unknown update.")
        return _to_record(row)


def is_approved(
    *,
    client_id: str,
    update_id: str,
    model_version: str,
    round_number: int,
    payload_sha256: str,
) -> bool:
    """Verify approval for the exact payload, model, and training round."""
    if not _SHA256_PATTERN.fullmatch(payload_sha256):
        return False

    with SessionLocal() as db:
        row = db.scalar(
            select(UpdateApproval.id).where(
                UpdateApproval.client_id == client_id,
                UpdateApproval.update_id == update_id,
                UpdateApproval.model_version == model_version,
                UpdateApproval.round_number == round_number,
                UpdateApproval.payload_sha256 == payload_sha256.lower(),
                UpdateApproval.status == UpdateStatus.APPROVED.value,
            )
        )
        return row is not None


def clear_approval_registry() -> None:
    """Delete all approval rows for development/test cleanup only."""
    with SessionLocal() as db:
        with db.begin():
            db.execute(delete(UpdateApproval))
