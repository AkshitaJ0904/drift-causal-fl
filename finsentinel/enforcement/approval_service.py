
"""Database-backed approval lifecycle for federated-learning updates."""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Text, cast, delete, func, select, update
from sqlalchemy.exc import IntegrityError

from audit.outbox import enqueue as _enqueue_outbox
from core.config import TRUST_MODE_COORDINATOR_VERIFIED, get_sample_count_trust_mode
from core.supabase.session import SessionLocal
from db.models.audit_event import AuditEvent
from db.models.replay_record import ReplayRecord
from db.models.update_approval import UpdateApproval
from ingestion.sample_count_provider import (
    PROVENANCE_PROVIDER_VERIFIED as _PROVENANCE_PROVIDER_VERIFIED,
)
from ingestion.sample_count_provider import (
    SampleCountResult,
)

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")

_STATE_AUDIT: dict[str, tuple[str, str]] = {
    "approved": ("operator.update_approved", "info"),
    "rejected": ("operator.update_rejected", "high"),
    "quarantined": ("operator.update_quarantined", "high"),
}


class UpdateStatus(StrEnum):
    VALIDATED = "validated"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class ApprovalError(ValueError):
    """Raised when an update lifecycle operation is invalid."""


class InternalConsistencyError(ApprovalError):
    """Raised when an internal state invariant is violated (maps to HTTP 500)."""


@dataclass(frozen=True)
class UpdateRecord:
    update_id: str
    client_id: str
    model_version: str
    round_number: int
    sample_count: int | None
    sample_count_provenance: str | None
    payload_sha256: str | None
    risk_score: int | None
    risk_severity: str | None
    suspicious: bool | None
    anomaly_reasons: tuple[str, ...] | None
    detector_version: str | None
    detector_config: dict[str, object] | None
    audit_status: str | None
    audit_failures: tuple[str, ...] | None
    status: UpdateStatus
    reason: str


def _to_record(row: UpdateApproval) -> UpdateRecord:
    return UpdateRecord(
        update_id=row.update_id,
        client_id=row.client_id,
        model_version=row.model_version,
        round_number=row.round_number,
        sample_count=row.sample_count,
        sample_count_provenance=row.sample_count_provenance,
        payload_sha256=row.payload_sha256,
        risk_score=row.risk_score,
        risk_severity=row.risk_severity,
        suspicious=row.suspicious,
        anomaly_reasons=(
            tuple(row.anomaly_reasons) if row.anomaly_reasons is not None else None
        ),
        detector_version=row.detector_version,
        detector_config=(
            dict(row.detector_config) if row.detector_config is not None else None
        ),
        audit_status=row.audit_status,
        audit_failures=(
            tuple(row.audit_failures) if row.audit_failures is not None else None
        ),
        status=UpdateStatus(row.status),
        reason=row.reason,
    )


def register_validated_update(
    *,
    update_id: str,
    client_id: str,
    model_version: str,
    round_number: int,
    sample_count_result: SampleCountResult,
    payload_sha256: str,
    reason: str = "Security validation passed; approval is still required.",
    initial_status: UpdateStatus | str = UpdateStatus.PENDING_APPROVAL,
    risk_score: int,
    risk_severity: str,
    suspicious: bool,
    anomaly_reasons: Sequence[str],
    detector_version: str,
    detector_config: Mapping[str, object],
) -> UpdateRecord:
    """Register a validated payload in its initial review state.

    ``sample_count_result`` must be a :class:`SampleCountResult` produced by
    :func:`ingestion.sample_count_provider.resolve_sample_count`.  It carries
    the count and provenance as an inseparable pair so callers cannot supply an
    arbitrary provenance string without a matching provider result.
    """
    if not isinstance(sample_count_result, SampleCountResult):
        raise TypeError(
            "sample_count_result must be a SampleCountResult instance; "
            "construct one via resolve_sample_count() or "
            "SampleCountResult(count=N, provenance=PROVENANCE_CLIENT_CLAIMED)."
        )

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

    try:
        initial_status = UpdateStatus(initial_status)
    except ValueError as exc:
        raise ValueError("Initial status is invalid.") from exc

    if initial_status not in {
        UpdateStatus.PENDING_APPROVAL,
        UpdateStatus.QUARANTINED,
    }:
        raise ValueError(
            "Initial status must be pending approval or quarantined."
        )

    if (
        isinstance(risk_score, bool)
        or not isinstance(risk_score, int)
        or not 0 <= risk_score <= 100
    ):
        raise ValueError("risk_score must be an integer from 0 to 100.")
    if risk_severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        raise ValueError("risk_severity is invalid.")
    if not isinstance(suspicious, bool):
        raise ValueError("suspicious must be a boolean.")
    if (
        not isinstance(anomaly_reasons, Sequence)
        or isinstance(anomaly_reasons, (str, bytes))
        or any(
            not isinstance(item, str) or not item.strip()
            for item in anomaly_reasons
        )
    ):
        raise ValueError("anomaly_reasons must contain non-empty strings.")
    if not isinstance(detector_version, str) or not detector_version.strip():
        raise ValueError("detector_version is required.")
    if detector_config is None:
        raise ValueError("detector_config is required for a new update.")
    if not isinstance(detector_config, Mapping) or not detector_config or any(
        not isinstance(key, str) or not key
        for key in detector_config
    ):
        raise ValueError("detector_config must be a non-empty mapping with string keys.")
    try:
        normalized_detector_config = json.loads(
            json.dumps(dict(detector_config), allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("detector_config must contain finite JSON values.") from exc

    decision_reason = reason.strip() if reason and reason.strip() else (
        "Security validation passed; approval is still required."
    )

    row = UpdateApproval(
        update_id=update_id,
        client_id=client_id,
        model_version=model_version,
        round_number=round_number,
        sample_count=sample_count_result.count,
        sample_count_provenance=sample_count_result.provenance,
        payload_sha256=payload_sha256.lower(),
        risk_score=risk_score,
        risk_severity=risk_severity,
        suspicious=suspicious,
        anomaly_reasons=list(anomaly_reasons),
        detector_version=detector_version.strip(),
        detector_config=normalized_detector_config,
        audit_status="pending",
        audit_failures=[],
        status=initial_status.value,
        reason=decision_reason,
    )

    try:
        with SessionLocal() as db:
            with db.begin():
                db.add(row)
                db.flush()
            return _to_record(row)
    except IntegrityError as exc:
        raise ApprovalError("Update is already registered.") from exc


def register_and_finalize_validated_update(
    *,
    update_id: str,
    client_id: str,
    model_version: str,
    round_number: int,
    sample_count_result: SampleCountResult,
    payload_sha256: str,
    reason: str = "Security validation passed; approval is still required.",
    initial_status: UpdateStatus | str = UpdateStatus.PENDING_APPROVAL,
    risk_score: int,
    risk_severity: str,
    suspicious: bool,
    anomaly_reasons: Sequence[str],
    detector_version: str,
    detector_config: Mapping[str, object],
    reservation_token: str,
) -> UpdateRecord:
    """Register a validated update and atomically finalize its replay reservation.

    Both the update_approvals INSERT and the replay_records finalization UPDATE
    are committed in a single SQLAlchemy transaction.  Either both succeed or
    both roll back — there is no window where the approval row exists but the
    replay record remains unfinalized.

    ``sample_count_result`` must be a :class:`SampleCountResult` produced by
    :func:`ingestion.sample_count_provider.resolve_sample_count`.  Provenance
    is taken directly from the result object and cannot be overridden by the
    caller.

    Raises InternalConsistencyError (a subclass of ApprovalError) if the replay
    reservation record is missing, which causes the caller to release the
    reservation and raise ApprovalRegistrationError.
    """
    if not isinstance(sample_count_result, SampleCountResult):
        raise TypeError(
            "sample_count_result must be a SampleCountResult instance; "
            "construct one via resolve_sample_count() or "
            "SampleCountResult(count=N, provenance=PROVENANCE_CLIENT_CLAIMED)."
        )
    if not all(value.strip() for value in (update_id, client_id, model_version)):
        raise ValueError("Update, client, and model identifiers are required.")
    if round_number < 1:
        raise ValueError("round_number must be positive.")
    if not _SHA256_PATTERN.fullmatch(payload_sha256):
        raise ValueError("A valid SHA-256 payload digest is required.")
    try:
        initial_status = UpdateStatus(initial_status)
    except ValueError as exc:
        raise ValueError("Initial status is invalid.") from exc
    if initial_status not in {UpdateStatus.PENDING_APPROVAL, UpdateStatus.QUARANTINED}:
        raise ValueError("Initial status must be pending approval or quarantined.")
    if (
        isinstance(risk_score, bool)
        or not isinstance(risk_score, int)
        or not 0 <= risk_score <= 100
    ):
        raise ValueError("risk_score must be an integer from 0 to 100.")
    if risk_severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        raise ValueError("risk_severity is invalid.")
    if not isinstance(suspicious, bool):
        raise ValueError("suspicious must be a boolean.")
    if (
        not isinstance(anomaly_reasons, Sequence)
        or isinstance(anomaly_reasons, (str, bytes))
        or any(
            not isinstance(item, str) or not item.strip()
            for item in anomaly_reasons
        )
    ):
        raise ValueError("anomaly_reasons must contain non-empty strings.")
    if not isinstance(detector_version, str) or not detector_version.strip():
        raise ValueError("detector_version is required.")
    if detector_config is None:
        raise ValueError("detector_config is required for a new update.")
    if not isinstance(detector_config, Mapping) or not detector_config or any(
        not isinstance(key, str) or not key
        for key in detector_config
    ):
        raise ValueError("detector_config must be a non-empty mapping with string keys.")
    try:
        normalized_detector_config = json.loads(
            json.dumps(dict(detector_config), allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("detector_config must contain finite JSON values.") from exc

    decision_reason = reason.strip() if reason and reason.strip() else (
        "Security validation passed; approval is still required."
    )

    row = UpdateApproval(
        update_id=update_id,
        client_id=client_id,
        model_version=model_version,
        round_number=round_number,
        sample_count=sample_count_result.count,
        sample_count_provenance=sample_count_result.provenance,
        payload_sha256=payload_sha256.lower(),
        risk_score=risk_score,
        risk_severity=risk_severity,
        suspicious=suspicious,
        anomaly_reasons=list(anomaly_reasons),
        detector_version=detector_version.strip(),
        detector_config=normalized_detector_config,
        audit_status="pending",
        audit_failures=[],
        status=initial_status.value,
        reason=decision_reason,
    )

    try:
        with SessionLocal() as db:
            with db.begin():
                db.add(row)
                db.flush()
                result = db.execute(
                    update(ReplayRecord)
                    .where(
                        ReplayRecord.client_id == client_id,
                        ReplayRecord.update_id == update_id,
                    )
                    .values(finalized=True)
                )
                if result.rowcount != 1:  # type: ignore[attr-defined]
                    raise InternalConsistencyError(
                        "Replay reservation record not found during atomic "
                        "finalization; the reservation may not have been created."
                    )
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
                    *(
                        [
                            UpdateApproval.audit_status == "persisted",
                            UpdateApproval.risk_score.is_not(None),
                            UpdateApproval.risk_severity.is_not(None),
                            UpdateApproval.suspicious.is_not(None),
                            UpdateApproval.anomaly_reasons.is_not(None),
                            UpdateApproval.detector_version.is_not(None),
                            UpdateApproval.detector_config.is_not(None),
                            cast(UpdateApproval.detector_config, Text) != "{}",
                        ]
                        if new_status == UpdateStatus.APPROVED
                        else []
                    ),
                )
                .values(
                    status=new_status.value,
                    reason=reason.strip(),
                    updated_at=func.now(),
                    decided_at=func.now(),
                )
            )

            if result.rowcount != 1:  # type: ignore[attr-defined]
                existing = db.scalar(
                    select(UpdateApproval).where(
                        UpdateApproval.client_id == client_id,
                        UpdateApproval.update_id == update_id,
                    )
                )
                if existing is None:
                    raise ApprovalError("Unknown update.")
                if (
                    new_status == UpdateStatus.APPROVED
                    and existing.status == UpdateStatus.PENDING_APPROVAL.value
                    and (
                        existing.audit_status != "persisted"
                        or existing.risk_score is None
                        or existing.risk_severity is None
                        or existing.suspicious is None
                        or existing.anomaly_reasons is None
                        or existing.detector_version is None
                        or not existing.detector_config
                    )
                ):
                    raise ApprovalError(
                        "Cannot approve update without complete detection evidence "
                        "and persisted audit status."
                    )
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
                raise InternalConsistencyError(
                    "Update disappeared during its state transition."
                )

            record = _to_record(row)

            # Write the state-change audit event in the same transaction so
            # that the state transition and its audit record are atomic.  Any
            # caller — API or direct service call — always leaves a durable
            # audit trail.
            event_type, severity = _STATE_AUDIT[new_status.value]
            audit_description = f"{new_status.value}: {reason[:500]}"
            audit_event = AuditEvent(
                event_type=event_type,
                severity=severity,
                client_id=client_id,
                update_id=update_id,
                description=audit_description,
            )
            db.add(audit_event)
            db.flush()  # populate audit_event.id for the outbox FK
            _enqueue_outbox(
                db,
                event_id=audit_event.id,
                event_type=event_type,
                severity=severity,
                description=audit_description,
                client_id=client_id,
                update_id=update_id,
            )

    return record


def record_ingestion_audit_result(
    *,
    client_id: str,
    update_id: str,
    audit_status: str,
    audit_failures: Sequence[str],
) -> UpdateRecord:
    """Persist the final audit outcome for a newly ingested update."""
    if audit_status not in {"persisted", "failed"}:
        raise ValueError("Final audit status must be persisted or failed.")
    if (
        not isinstance(audit_failures, Sequence)
        or isinstance(audit_failures, (str, bytes))
        or any(not isinstance(item, str) or not item.strip() for item in audit_failures)
    ):
        raise ValueError("audit_failures must contain non-empty event names.")

    with SessionLocal() as db:
        with db.begin():
            row = db.scalar(
                select(UpdateApproval)
                .where(
                    UpdateApproval.client_id == client_id,
                    UpdateApproval.update_id == update_id,
                    UpdateApproval.status.in_(
                        [
                            UpdateStatus.PENDING_APPROVAL.value,
                            UpdateStatus.QUARANTINED.value,
                        ]
                    ),
                )
                .with_for_update()
            )
            if row is None:
                raise ApprovalError("Ingested update was not found for audit update.")

            row.audit_status = audit_status
            row.audit_failures = list(audit_failures)
            if audit_status == "failed" and "AUDIT_PERSISTENCE_FAILED" not in row.reason:
                row.reason += (
                    " [AUDIT_PERSISTENCE_FAILED for: "
                    f"{', '.join(audit_failures) or 'audit outcome could not be confirmed'}]"
                )
            record = _to_record(row)

    return record


def approve_update(
    *,
    client_id: str,
    update_id: str,
    reason: str,
    require_verified_provenance: bool | None = None,
) -> UpdateRecord:
    """Approve a pending update for the enforcement stage.

    When *require_verified_provenance* is True (or when the deployment is in
    ``coordinator_verified`` mode), updates whose persisted
    ``sample_count_provenance`` is not ``'provider_verified'`` are rejected
    before the state transition is attempted.
    """
    _require_verified = require_verified_provenance
    if _require_verified is None:
        _require_verified = get_sample_count_trust_mode() == TRUST_MODE_COORDINATOR_VERIFIED

    if _require_verified:
        record = get_update_record(client_id=client_id, update_id=update_id)
        if record.sample_count_provenance != _PROVENANCE_PROVIDER_VERIFIED:
            raise ApprovalError(
                "Cannot approve update: sample_count_provenance is "
                f"{record.sample_count_provenance!r}, not 'provider_verified'. "
                "In coordinator_verified mode only updates with provider-verified "
                "sample counts may be approved."
            )

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
    sample_count: int | None = None,
    require_verified_provenance: bool = False,
) -> bool:
    """Verify approval for the exact payload, model, and training round.

    When *require_verified_provenance* is True, only approvals whose
    ``sample_count_provenance`` equals ``"provider_verified"`` are considered
    valid.  Client-claimed counts stored with ``"client_claimed"`` provenance
    return False even if all other fields match.
    """
    if (
        not _SHA256_PATTERN.fullmatch(payload_sha256)
        or isinstance(sample_count, bool)
        or not isinstance(sample_count, int)
        or sample_count <= 0
    ):
        return False

    provenance_filter = (
        [UpdateApproval.sample_count_provenance == _PROVENANCE_PROVIDER_VERIFIED]
        if require_verified_provenance
        else []
    )

    with SessionLocal() as db:
        row = db.scalar(
            select(UpdateApproval.id).where(
                UpdateApproval.client_id == client_id,
                UpdateApproval.update_id == update_id,
                UpdateApproval.model_version == model_version,
                UpdateApproval.round_number == round_number,
                UpdateApproval.sample_count == sample_count,
                UpdateApproval.payload_sha256 == payload_sha256.lower(),
                UpdateApproval.status == UpdateStatus.APPROVED.value,
                UpdateApproval.risk_score.is_not(None),
                UpdateApproval.risk_severity.is_not(None),
                UpdateApproval.suspicious.is_not(None),
                UpdateApproval.anomaly_reasons.is_not(None),
                UpdateApproval.detector_version.is_not(None),
                UpdateApproval.detector_config.is_not(None),
                cast(UpdateApproval.detector_config, Text) != "{}",
                UpdateApproval.audit_status == "persisted",
                *provenance_filter,
            )
        )
        return row is not None


def list_pending_updates(*, limit: int = 100) -> list[UpdateRecord]:
    """Return up to *limit* records whose status is ``pending_approval``.

    Results are ordered by primary-key insertion order so the oldest
    submissions are returned first.
    """
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("limit must be an integer.")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000.")
    with SessionLocal() as db:
        rows = db.scalars(
            select(UpdateApproval)
            .where(UpdateApproval.status == UpdateStatus.PENDING_APPROVAL.value)
            .order_by(UpdateApproval.id)
            .limit(limit)
        ).all()
    return [_to_record(row) for row in rows]


def clear_approval_registry() -> None:
    """Delete all approval rows for development/test cleanup only."""
    with SessionLocal() as db:
        with db.begin():
            db.execute(delete(UpdateApproval))
