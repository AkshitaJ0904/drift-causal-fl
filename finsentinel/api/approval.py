
"""HTTP API for operator approval lifecycle of validated updates.

Authentication: every endpoint requires a bearer token matching the value
of FINSENTINEL_OPERATOR_TOKEN.  When that variable is unset the endpoint
returns 503 so callers can distinguish "auth not configured" from
"bad credentials".

Decisions are auditable: each transition records an audit event in
addition to the state change written by the approval service.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from api._auth import require_operator_auth, validate_path_id
from audit.service import record_audit_event
from enforcement.approval_service import (
    ApprovalError,
    InternalConsistencyError,
    UpdateRecord,
    approve_update,
    get_update_record,
    list_pending_updates,
    quarantine_update,
    reject_update,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/updates", tags=["approval"])

# Approval-related audit events are "info" (normal workflow).
# Reject/quarantine events are "high" (security-significant negative actions).
_AUDIT_SEVERITY: dict[str, str] = {
    "operator.approve_requested": "info",
    "operator.update_approved": "info",
    "operator.reject_requested": "high",
    "operator.update_rejected": "high",
    "operator.quarantine_requested": "high",
    "operator.update_quarantined": "high",
}


def _record_to_dict(record: UpdateRecord) -> dict[str, Any]:
    return {
        "update_id": record.update_id,
        "client_id": record.client_id,
        "model_version": record.model_version,
        "round_number": record.round_number,
        "sample_count": record.sample_count,
        "payload_sha256": record.payload_sha256,
        "status": record.status.value,
        "risk_score": record.risk_score,
        "risk_severity": record.risk_severity,
        "suspicious": record.suspicious,
        "anomaly_reasons": list(record.anomaly_reasons) if record.anomaly_reasons else [],
        "audit_status": record.audit_status,
        "reason": record.reason,
    }


def _audit_operator_decision(
    *,
    event_type: str,
    client_id: str,
    update_id: str,
    reason: str,
    critical: bool = False,
) -> None:
    """Persist an operator decision audit event.

    When ``critical=True`` (pre-decision), an audit failure raises HTTP 503
    to block the decision from proceeding without an audit trail.
    When ``critical=False`` (post-decision), failures are only logged.
    """
    try:
        record_audit_event(
            event_type=event_type,
            severity=_AUDIT_SEVERITY.get(event_type, "info"),
            description=f"Operator decision — {reason[:500]}",
            client_id=client_id,
            update_id=update_id,
        )
    except Exception as exc:
        if critical:
            logger.error(
                "Critical pre-decision audit event %s could not be persisted "
                "for %s/%s; blocking decision.",
                event_type,
                client_id,
                update_id,
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "Audit service unavailable. "
                    "The decision cannot be recorded and has been blocked."
                ),
            ) from exc
        logger.warning(
            "Post-decision audit event %s could not be persisted for %s/%s",
            event_type,
            client_id,
            update_id,
        )


@router.get("/pending")
def list_pending_updates_endpoint(request: Request) -> dict[str, Any]:
    """Return all updates currently awaiting operator approval.

    Results are ordered oldest-first and capped at 100 records.
    Requires operator authentication.
    """
    require_operator_auth(request)
    records = list_pending_updates()
    return {"pending": [_record_to_dict(r) for r in records]}


@router.get("/{client_id}/{update_id}/status")
def get_update_status(
    client_id: str,
    update_id: str,
    request: Request,
) -> dict[str, Any]:
    """Return the current lifecycle record for an update."""
    require_operator_auth(request)
    validate_path_id(client_id, "client_id")
    validate_path_id(update_id, "update_id")
    try:
        record = get_update_record(client_id=client_id, update_id=update_id)
    except ApprovalError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _record_to_dict(record)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/{client_id}/{update_id}/approve")
def approve_update_endpoint(
    client_id: str,
    update_id: str,
    body: DecisionRequest,
    request: Request,
) -> dict[str, Any]:
    """Approve a pending update for aggregation.

    Approval requires complete detection evidence and a persisted audit
    status.  High-risk and critical-risk updates are quarantined by
    default during ingestion and cannot be approved from the
    pending_approval status (they never enter it).
    """
    require_operator_auth(request)
    validate_path_id(client_id, "client_id")
    validate_path_id(update_id, "update_id")
    _audit_operator_decision(
        event_type="operator.approve_requested",
        client_id=client_id,
        update_id=update_id,
        reason=body.reason,
        critical=True,
    )
    try:
        record = approve_update(
            client_id=client_id,
            update_id=update_id,
            reason=body.reason,
        )
    except InternalConsistencyError as exc:
        raise HTTPException(status_code=500, detail="Internal state inconsistency.") from exc
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _record_to_dict(record)


@router.post("/{client_id}/{update_id}/reject")
def reject_update_endpoint(
    client_id: str,
    update_id: str,
    body: DecisionRequest,
    request: Request,
) -> dict[str, Any]:
    """Reject a pending update."""
    require_operator_auth(request)
    validate_path_id(client_id, "client_id")
    validate_path_id(update_id, "update_id")
    _audit_operator_decision(
        event_type="operator.reject_requested",
        client_id=client_id,
        update_id=update_id,
        reason=body.reason,
        critical=True,
    )
    try:
        record = reject_update(
            client_id=client_id,
            update_id=update_id,
            reason=body.reason,
        )
    except InternalConsistencyError as exc:
        raise HTTPException(status_code=500, detail="Internal state inconsistency.") from exc
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _record_to_dict(record)


@router.post("/{client_id}/{update_id}/quarantine")
def quarantine_update_endpoint(
    client_id: str,
    update_id: str,
    body: DecisionRequest,
    request: Request,
) -> dict[str, Any]:
    """Move a pending update to quarantine."""
    require_operator_auth(request)
    validate_path_id(client_id, "client_id")
    validate_path_id(update_id, "update_id")
    _audit_operator_decision(
        event_type="operator.quarantine_requested",
        client_id=client_id,
        update_id=update_id,
        reason=body.reason,
        critical=True,
    )
    try:
        record = quarantine_update(
            client_id=client_id,
            update_id=update_id,
            reason=body.reason,
        )
    except InternalConsistencyError as exc:
        raise HTTPException(status_code=500, detail="Internal state inconsistency.") from exc
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _record_to_dict(record)
