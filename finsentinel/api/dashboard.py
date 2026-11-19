"""Operator dashboard endpoint — authenticated summary of service state.

Requires the FINSENTINEL_OPERATOR_TOKEN bearer token.
Never exposes credentials, keys, secrets, or payload content.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Request

from api._auth import require_operator_auth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["operator"])


@router.get(
    "/operator/dashboard",
    dependencies=[Depends(require_operator_auth)],
)
def operator_dashboard(request: Request) -> dict[str, object]:
    """Return a structured operational summary for the operator.

    Sections
    --------
    outbox:
        Pending and dead-lettered audit event counts.
    registries:
        Trusted key count and registered model schema count.
    approvals:
        Pending approval queue depth (updates awaiting operator decision).
    worker:
        Audit delivery worker configuration state.
    config:
        Applied resource limits (caps, rate limits, timeouts).

    Security contract
    -----------------
    - All fields are counts, booleans, or opaque configuration values.
    - No key material, tokens, payloads, or client data are returned.
    - Operator authentication is enforced via ``require_operator_auth``.
    """
    result: dict[str, object] = {}

    # --- Outbox ---
    outbox_pending: int | None = None
    outbox_dead_letter: int | None = None
    outbox_error: str | None = None
    try:
        from audit.outbox import dead_letter_count, pending_count
        outbox_pending = pending_count()
        outbox_dead_letter = dead_letter_count()
    except Exception as exc:
        outbox_error = type(exc).__name__
        logger.warning("Dashboard: outbox metrics unavailable: %s", exc)

    result["outbox"] = {
        "pending_count": outbox_pending,
        "dead_letter_count": outbox_dead_letter,
        "error": outbox_error,
        "alert": (
            outbox_dead_letter is not None and outbox_dead_letter > 0
        ),
    }

    # --- Registries ---
    trusted_key_count: int | None = None
    model_schema_count: int | None = None
    registries_error: str | None = None
    try:
        from core.supabase.session import SessionLocal
        from db.models.trusted_key import TrustedKeyRecord as TrustedKey
        from db.models.trusted_model_schema import TrustedModelSchema as ModelSchema

        with SessionLocal() as db:
            trusted_key_count = db.query(TrustedKey).count()
            model_schema_count = db.query(ModelSchema).count()
    except Exception as exc:
        registries_error = type(exc).__name__
        logger.warning("Dashboard: registry metrics unavailable: %s", exc)

    result["registries"] = {
        "trusted_key_count": trusted_key_count,
        "model_schema_count": model_schema_count,
        "error": registries_error,
    }

    # --- Approvals ---
    pending_approval_count: int | None = None
    approvals_error: str | None = None
    try:
        from core.supabase.session import SessionLocal as _SessionLocal
        from db.models.update_approval import UpdateApproval
        from enforcement.approval_service import UpdateStatus

        with _SessionLocal() as db:
            pending_approval_count = (
                db.query(UpdateApproval)
                .filter(UpdateApproval.status == UpdateStatus.PENDING_APPROVAL.value)
                .count()
            )
    except Exception as exc:
        approvals_error = type(exc).__name__
        logger.warning("Dashboard: approval metrics unavailable: %s", exc)

    result["approvals"] = {
        "pending_count": pending_approval_count,
        "error": approvals_error,
    }

    # --- Worker and delivery config ---
    import os
    worker_enabled_raw = os.getenv("FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED", "").strip().lower()
    worker_enabled = worker_enabled_raw in ("1", "true", "yes")
    webhook_url_configured = bool(os.getenv("FINSENTINEL_AUDIT_WEBHOOK_URL", "").strip())

    result["worker"] = {
        "enabled": worker_enabled,
        "webhook_configured": webhook_url_configured,
    }

    # --- Applied resource limits ---
    from core.concurrency import get_ingestion_cap
    from core.rate_limit import get_rate_limit

    result["config"] = {
        "concurrency_cap": get_ingestion_cap(),
        "rate_limit_rpm": get_rate_limit(),
        "body_read_timeout_seconds": _float_env("FINSENTINEL_BODY_READ_TIMEOUT_SECONDS"),
        "operator_token_configured": bool(
            os.getenv("FINSENTINEL_OPERATOR_TOKEN", "").strip()
        ),
    }

    # --- Detection thresholds ---
    detection_thresholds: dict[str, float | None] | None = None
    detection_error: str | None = None
    try:
        from core.config import get_detection_config
        dc = get_detection_config()
        detection_thresholds = {
            "max_weight_l2_norm": dc.max_weight_l2_norm,
            "max_update_l2_norm": dc.max_update_l2_norm,
            "max_weight_abs_mean": dc.max_weight_abs_mean,
            "max_weight_std": dc.max_weight_std,
            "max_weight_zero_fraction": dc.max_weight_zero_fraction,
            "min_weight_zero_fraction": dc.min_weight_zero_fraction,
        }
    except Exception as exc:
        detection_error = type(exc).__name__
        logger.warning("Dashboard: detection config unavailable: %s", exc)

    result["detection"] = {
        "thresholds": detection_thresholds,
        "error": detection_error,
        "high_risk_action": os.getenv("FINSENTINEL_HIGH_RISK_ACTION", "quarantined"),
    }

    return result


def _float_env(name: str) -> float | None:
    val = os.getenv(name, "").strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None
