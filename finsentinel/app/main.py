
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.aggregation import router as aggregation_router
from api.approval import router as approval_router
from api.dashboard import router as dashboard_router
from api.health import router as health_router
from api.ingestion import router as ingestion_router
from api.security_events import router as security_events_router
from api.vapt_report import router as vapt_report_router
from core.concurrency import configure_ingestion_cap, get_ingestion_cap
from core.config import (
    TRUST_MODE_COORDINATOR_VERIFIED,
    get_sample_count_trust_mode,
    get_settings,
)
from core.middleware import (
    IngestionConcurrencyMiddleware,
    IngestionRateLimitMiddleware,
    RequestBodyLimitMiddleware,
)
from core.rate_limit import configure_rate_limit, get_rate_limit

logger = logging.getLogger(__name__)

settings = get_settings()

def _validate_trust_mode_configuration(trust_mode: str) -> None:
    """Fail startup if coordinator_verified mode has no configured provider.

    Checks the module-level ``_sample_count_provider`` in
    ``ingestion.service``.  Raises :class:`RuntimeError` when the mode is
    ``coordinator_verified`` and no provider has been registered via
    :func:`ingestion.service.configure_sample_count_provider`.
    """
    if trust_mode == TRUST_MODE_COORDINATOR_VERIFIED:
        # Import here to defer until after configure_sample_count_provider()
        # has had a chance to run.
        from ingestion.service import _sample_count_provider as _sc_provider  # noqa: PLC2701
        if _sc_provider is None:
            raise RuntimeError(
                "FINSENTINEL_SAMPLE_COUNT_TRUST_MODE=coordinator_verified requires "
                "a sample-count provider to be configured before startup. "
                "Call configure_sample_count_provider() with a trusted provider "
                "before this module is imported."
            )
        logger.info(
            "Sample-count trust mode: coordinator_verified "
            "(provider=%r). CLIENT_CLAIMED updates will be rejected.",
            getattr(_sc_provider, "name", repr(_sc_provider)),
        )
    else:
        logger.warning(
            "Sample-count trust mode: client_claimed "
            "(FINSENTINEL_SAMPLE_COUNT_TRUST_MODE not set or 'client_claimed'). "
            "Sample counts are accepted from clients without independent verification."
        )


_validate_trust_mode_configuration(get_sample_count_trust_mode())

# S0-1: Warn if operator auth token is absent — protected endpoints will 503 without it.
if not os.getenv("FINSENTINEL_OPERATOR_TOKEN", "").strip():
    logger.warning(
        "Operator authentication token not configured "
        "(FINSENTINEL_OPERATOR_TOKEN unset or empty). "
        "All operator-authenticated endpoints will return HTTP 503 until this is set."
    )
else:
    # S0-1b: Error if token is configured but too short (brute-force risk).
    from api._auth import check_operator_token_strength
    check_operator_token_strength()

# S0-9: Warn if audit delivery worker is not enabled.
if not os.getenv("FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED", "").strip():
    logger.warning(
        "Audit delivery worker not enabled "
        "(FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED not set). "
        "Audit events will accumulate in the outbox but will not be forwarded externally."
    )

_max_concurrent_ingestion = os.getenv("FINSENTINEL_MAX_CONCURRENT_INGESTION")
if _max_concurrent_ingestion is not None and _max_concurrent_ingestion.strip():
    try:
        configure_ingestion_cap(int(_max_concurrent_ingestion.strip()))
    except ValueError as exc:
        raise ValueError(
            "FINSENTINEL_MAX_CONCURRENT_INGESTION must be a positive integer. "
            f"Got: {_max_concurrent_ingestion!r}"
        ) from exc

_cap = get_ingestion_cap()
if _cap is not None:
    logger.info(
        "Concurrent-ingestion cap: %d per-process worker "
        "(FINSENTINEL_MAX_CONCURRENT_INGESTION=%d). "
        "This limit is NOT shared across multiple uvicorn workers.",
        _cap,
        _cap,
    )
else:
    logger.warning(
        "Concurrent-ingestion cap: unlimited "
        "(FINSENTINEL_MAX_CONCURRENT_INGESTION not set). "
        "Set this variable to a positive integer before production deployment."
    )

@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start optional background services on startup; stop them on shutdown."""
    worker = None
    _worker_enabled = os.getenv("FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED", "")
    if _worker_enabled.strip().lower() in ("1", "true", "yes"):
        from audit.delivery import DeliveryConfigError, create_webhook_delivery_fn
        from audit.worker import OutboxDeliveryWorker

        delivery_fn = None
        _webhook_url = os.getenv("FINSENTINEL_AUDIT_WEBHOOK_URL", "").strip()
        _webhook_token = os.getenv("FINSENTINEL_AUDIT_WEBHOOK_TOKEN", "").strip()

        if _webhook_url:
            try:
                delivery_fn = create_webhook_delivery_fn(
                    url=_webhook_url,
                    token=_webhook_token or None,
                )
                logger.info(
                    "Audit webhook delivery configured (url=%s).",
                    _webhook_url,
                )
            except DeliveryConfigError as exc:
                # Invalid URL is a fatal configuration error — fail startup.
                raise RuntimeError(
                    f"Invalid FINSENTINEL_AUDIT_WEBHOOK_URL: {exc}"
                ) from exc
        else:
            logger.warning(
                "Audit delivery worker enabled but FINSENTINEL_AUDIT_WEBHOOK_URL is not set. "
                "Events will accumulate as pending without being forwarded."
            )

        worker = OutboxDeliveryWorker(delivery_fn=delivery_fn)
        worker.start()

    # S0-2: Warn on startup if any events are already dead-lettered.
    try:
        from audit.outbox import dead_letter_count as _dead_letter_count
        _dl = _dead_letter_count()
        if _dl > 0:
            logger.warning(
                "Startup: %d dead-lettered audit event(s) found. "
                "These records exceeded MAX_DELIVERY_ATTEMPTS and require manual investigation.",
                _dl,
            )
    except Exception:
        logger.warning(
            "Startup: could not query outbox dead-letter count — "
            "database may not be reachable yet."
        )

    yield

    if worker is not None:
        worker.stop(timeout=10.0)


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Security platform for federated-learning model updates.",
    lifespan=_lifespan,
)

_rate_limit_env = os.getenv("FINSENTINEL_INGESTION_RATE_LIMIT_RPM")
if _rate_limit_env is not None and _rate_limit_env.strip():
    try:
        configure_rate_limit(int(_rate_limit_env.strip()))
    except ValueError as exc:
        raise ValueError(
            "FINSENTINEL_INGESTION_RATE_LIMIT_RPM must be a positive integer. "
            f"Got: {_rate_limit_env!r}"
        ) from exc

_rl = get_rate_limit()
if _rl is not None:
    logger.info(
        "Ingestion rate limit: %d requests/minute per source IP "
        "(FINSENTINEL_INGESTION_RATE_LIMIT_RPM=%d). "
        "PROCESS-LOCAL ONLY — not shared across uvicorn workers. "
        "Configure nginx limit_req for cluster-wide enforcement.",
        _rl,
        _rl,
    )
else:
    logger.warning(
        "Ingestion rate limit: not configured (FINSENTINEL_INGESTION_RATE_LIMIT_RPM not set). "
        "No application-layer rate limiting. "
        "Configure nginx limit_req for production rate limiting."
    )

_body_read_timeout_env = os.getenv("FINSENTINEL_BODY_READ_TIMEOUT_SECONDS")
_body_read_timeout: float | None = None
if _body_read_timeout_env is not None and _body_read_timeout_env.strip():
    try:
        _body_read_timeout = float(_body_read_timeout_env.strip())
        if _body_read_timeout <= 0:
            raise ValueError("must be positive")
    except ValueError as exc:
        raise ValueError(
            "FINSENTINEL_BODY_READ_TIMEOUT_SECONDS must be a positive number. "
            f"Got: {_body_read_timeout_env!r}"
        ) from exc

if _body_read_timeout is not None:
    logger.info(
        "Body-read timeout: %.1f s (FINSENTINEL_BODY_READ_TIMEOUT_SECONDS=%.1f). "
        "Covers the ASGI body-read phase only. "
        "When deployed behind a buffering reverse proxy (e.g. nginx), also set "
        "client_body_timeout in the proxy to protect the client-to-proxy leg.",
        _body_read_timeout,
        _body_read_timeout,
    )
else:
    logger.warning(
        "Body-read timeout: not set (FINSENTINEL_BODY_READ_TIMEOUT_SECONDS not configured). "
        "No application-layer deadline on body reads. "
        "Set this in production and configure client_body_timeout in the reverse proxy."
    )

# Middleware registration order: last-registered = outermost = first to run.
# 1. RequestBodyLimitMiddleware  (registered first → innermost: body limit + timeout)
# 2. IngestionConcurrencyMiddleware (registered 2nd → outer: slot gate before body read)
# 3. IngestionRateLimitMiddleware  (registered last → outermost: cheap IP check first)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_size=10_000_000,
    body_read_timeout_seconds=_body_read_timeout,
)
app.add_middleware(IngestionConcurrencyMiddleware)
app.add_middleware(IngestionRateLimitMiddleware)

app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(ingestion_router, prefix=settings.api_prefix)
app.include_router(approval_router, prefix=settings.api_prefix)
app.include_router(aggregation_router, prefix=settings.api_prefix)
app.include_router(dashboard_router, prefix=settings.api_prefix)
app.include_router(security_events_router, prefix=settings.api_prefix)
app.include_router(vapt_report_router, prefix=settings.api_prefix)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "running"}
