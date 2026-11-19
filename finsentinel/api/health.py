"""Health and operational-metrics endpoints.

The /health endpoint returns a lightweight liveness check with no DB access.
The /health/metrics endpoint returns operational counters and configuration
state for monitoring.  It never exposes credentials, tokens, signing keys,
or sensitive payload data.
The /health/alerts endpoint returns a structured alert list suitable for
external monitoring tools (Prometheus alert manager, PagerDuty webhooks,
uptime checks, etc.).  It requires no authentication so monitoring agents
can poll it without operator credentials — but it intentionally omits
sensitive detail.
"""

import logging

from fastapi import APIRouter, Depends

from api._auth import require_operator_auth
from core.concurrency import get_ingestion_cap
from core.config import get_settings
from core.rate_limit import get_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    settings = get_settings()

    return {
        "status": "ok",
        "service": settings.app_name,
    }


@router.get("/health/metrics", dependencies=[Depends(require_operator_auth)])
def health_metrics() -> dict[str, object]:
    """Operational metrics for monitoring and incident response.

    Returns queue depths, resource-limit configuration, and middleware
    settings.  No credentials, tokens, keys, or payloads are included.

    Callers should not interpret an error from this endpoint as a service
    outage — the main ingestion path does not depend on this route.
    """
    outbox_pending: int | None = None
    outbox_dead_letter: int | None = None
    outbox_error: str | None = None

    try:
        from audit.outbox import dead_letter_count, pending_count

        outbox_pending = pending_count()
        outbox_dead_letter = dead_letter_count()
    except Exception as exc:
        outbox_error = type(exc).__name__
        logger.warning("Outbox metrics unavailable: %s", exc)

    ingestion_cap = get_ingestion_cap()
    rate_limit_rpm = get_rate_limit()

    return {
        "outbox": {
            "pending_count": outbox_pending,
            "dead_letter_count": outbox_dead_letter,
            "error": outbox_error,
        },
        "ingestion": {
            "concurrency_cap": ingestion_cap,
            "concurrency_cap_scope": "process-local"
            if ingestion_cap is not None
            else None,
        },
        "rate_limit": {
            "requests_per_minute": rate_limit_rpm,
            "scope": "process-local" if rate_limit_rpm is not None else None,
            "note": (
                "Per-IP, per-process only. For cluster-wide enforcement "
                "configure nginx limit_req."
            ),
        },
    }


@router.get("/health/alerts")
def health_alerts() -> dict[str, object]:
    """Structured operational alert list for external monitoring integration.

    Returns a machine-readable list of active alerts, suitable for:
    - HTTP-based uptime monitors (checks for status != "ok")
    - Alertmanager / PagerDuty webhook integrations
    - Simple shell scripts polling the deployment

    No operator authentication is required so monitoring agents can poll
    this endpoint without storing the operator token.  The response omits
    sensitive data: no queue contents, payload data, tokens, or keys.

    Response shape:
    {
      "status": "ok" | "degraded",
      "alerts": [
        {
          "type": str,       # machine-readable alert identifier
          "severity": str,   # "warning" | "critical"
          "count": int,      # affected item count (0 when resolved)
          "message": str     # human-readable description
        }
      ]
    }

    HTTP 200 is always returned (including when status == "degraded") so
    that uptime monitors can read the JSON body.  An HTTP error from this
    endpoint indicates the service itself is unresponsive, not merely in a
    degraded state.
    """
    alerts: list[dict] = []
    status = "ok"

    try:
        from audit.outbox import dead_letter_count

        dl_count = dead_letter_count()
        if dl_count > 0:
            status = "degraded"
            alerts.append(
                {
                    "type": "dead_letter_accumulation",
                    "severity": "warning",
                    "count": dl_count,
                    "message": (
                        f"{dl_count} audit event(s) could not be delivered "
                        "and have been moved to the dead-letter queue. "
                        "Check FINSENTINEL_AUDIT_WEBHOOK_URL configuration "
                        "and the operator dashboard for details."
                    ),
                }
            )
    except Exception as exc:
        status = "degraded"
        alerts.append(
            {
                "type": "outbox_unavailable",
                "severity": "critical",
                "count": 0,
                "message": "Dead-letter check failed; outbox state is unknown.",
            }
        )
        logger.warning("Alert check: outbox unavailable: %s", exc)

    return {"status": status, "alerts": alerts}
