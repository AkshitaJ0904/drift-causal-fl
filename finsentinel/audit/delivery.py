"""Webhook delivery adapter for the transactional audit-event outbox.

Provides a synchronous delivery function that POSTs audit event payloads to
a configured HTTPS endpoint using canonical httpx.

Security contract
-----------------
- The delivery URL must use HTTPS unless it resolves to localhost or 127.0.0.1
  (loopback-only exception for local development and integration tests).
- Certificate verification is always enabled.  It cannot be disabled at runtime.
- The bearer token is read once at construction and never logged.
- The token is compared server-side only; it is never echoed in error messages.
- Connection, read, and write timeouts are bounded to prevent delivery threads
  from blocking the worker indefinitely.

Payload schema version: "1"
Fields: idempotency_key, schema_version, service, event_type, severity,
        client_id, update_id, description, event_id, attempt_count, created_at.

At-least-once delivery
----------------------
If the HTTP call succeeds (2xx) but the acknowledgment DB write fails, the
outbox claim TTL will expire and the record will be re-claimed and delivered
again.  Receivers MUST deduplicate on idempotency_key.

Error handling
--------------
- Connection error or timeout → raises exception → caller triggers backoff.
- HTTP 4xx (client error) → raises DeliveryPermanentError → bypasses backoff;
  the record is dead-lettered immediately to prevent retrying a bad payload.
- HTTP 5xx (server error) → raises exception → caller triggers backoff.
- HTTP 2xx → success, no exception raised.

SSRF mitigation
---------------
The URL is validated at construction time.  Only HTTPS endpoints are accepted
for non-loopback hosts.  Private-network IP blocking is documented as a
deployment-layer concern (nginx or firewall rules) since DNS-resolution-based
checks are race-prone.  Operators MUST configure network-level controls to
prevent delivery to internal services.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
SERVICE_NAME = "finsentinel"

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

# Bounded timeouts: connect 5 s, read/write 15 s each.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)


class DeliveryConfigError(ValueError):
    """Raised when the delivery adapter cannot be constructed from configuration."""


class DeliveryPermanentError(RuntimeError):
    """Raised when the server returns a 4xx response (non-retryable).

    The outbox record should be moved directly to dead_letter rather than
    undergoing exponential backoff, since retrying will not resolve the
    underlying data or authentication problem.
    """


def _validate_webhook_url(url: str) -> None:
    """Validate URL for SSRF safety and scheme requirement.

    Raises
    ------
    DeliveryConfigError
        If the URL is empty, uses a non-HTTP scheme, or uses plain HTTP
        for a non-loopback host.
    """
    if not url or not url.strip():
        raise DeliveryConfigError("FINSENTINEL_AUDIT_WEBHOOK_URL must not be empty.")

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise DeliveryConfigError(
            f"FINSENTINEL_AUDIT_WEBHOOK_URL scheme must be http or https; got {parsed.scheme!r}. "
            "Only HTTPS is accepted for non-loopback endpoints."
        )

    if parsed.scheme == "http":
        host = (parsed.hostname or "").lower()
        if host not in _LOOPBACK_HOSTS:
            raise DeliveryConfigError(
                "FINSENTINEL_AUDIT_WEBHOOK_URL uses plain HTTP for a non-loopback host. "
                f"Host {host!r} requires HTTPS to protect the bearer token and payload in transit. "
                "Use https:// or change the endpoint."
            )

    if not parsed.netloc:
        raise DeliveryConfigError(
            "FINSENTINEL_AUDIT_WEBHOOK_URL has no host/netloc component."
        )


def create_webhook_delivery_fn(
    *,
    url: str,
    token: str | None = None,
    timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
) -> _WebhookDeliveryFn:
    """Build and return a delivery callable from configuration.

    Parameters
    ----------
    url:
        The HTTPS endpoint that receives POST requests.
    token:
        Bearer token sent in the Authorization header.  If empty or None, the
        Authorization header is omitted and the endpoint receives unauthenticated
        requests.  A warning is logged when the token is absent for a
        non-loopback endpoint.
    timeout:
        httpx Timeout for connect, read, write and pool operations.

    Returns
    -------
    A callable ``fn(payload: dict) -> None`` suitable for passing to
    ``OutboxDeliveryWorker(delivery_fn=fn)``.

    Raises
    ------
    DeliveryConfigError
        If *url* fails SSRF validation.
    """
    _validate_webhook_url(url)

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    is_loopback = host in _LOOPBACK_HOSTS

    if not token and not is_loopback:
        logger.warning(
            "Audit webhook delivery configured without an authentication token "
            "(FINSENTINEL_AUDIT_WEBHOOK_TOKEN not set). "
            "The endpoint will receive unauthenticated requests."
        )

    return _WebhookDeliveryFn(url=url, token=token or "", timeout=timeout)


class _WebhookDeliveryFn:
    """Synchronous HTTP delivery callable backed by httpx.

    Not intended to be constructed directly; use ``create_webhook_delivery_fn()``.

    Thread-safety: ``httpx.Client`` is not thread-safe for concurrent requests
    from multiple threads; the worker calls this sequentially within a single
    thread, so a single client instance is safe.
    """

    def __init__(
        self,
        *,
        url: str,
        token: str,
        timeout: httpx.Timeout,
    ) -> None:
        self._url = url
        self._token = token
        self._timeout = timeout
        # Build headers once; token is never logged or stored in a way that
        # exposes it through repr/str.
        self._headers = {"Content-Type": "application/json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

        # Create a persistent client for connection pooling.
        # verify=True is the default and cannot be disabled here.
        self._client = httpx.Client(
            headers=self._headers,
            timeout=self._timeout,
            follow_redirects=False,
        )

    def __call__(self, payload: dict) -> None:
        """Deliver *payload* via HTTP POST.

        Raises
        ------
        DeliveryPermanentError
            On HTTP 4xx responses (non-retryable; dead-letter the record).
        httpx.HTTPStatusError
            On HTTP 5xx responses (retryable via backoff).
        httpx.TimeoutException
            On connect/read/write timeout (retryable via backoff).
        httpx.RequestError
            On connection failure (retryable via backoff).
        """
        try:
            response = self._client.post(self._url, json=payload)
        except httpx.TimeoutException as exc:
            raise httpx.TimeoutException(
                f"Webhook delivery timed out for event_type={payload.get('event_type')!r}"
            ) from exc
        except httpx.RequestError as exc:
            raise httpx.RequestError(
                f"Webhook delivery connection error for event_type={payload.get('event_type')!r}: "
                f"{type(exc).__name__}"
            ) from exc

        if 400 <= response.status_code < 500:
            raise DeliveryPermanentError(
                f"Webhook delivery returned HTTP {response.status_code} for "
                f"event_type={payload.get('event_type')!r} "
                f"idempotency_key={payload.get('idempotency_key')!r}. "
                f"4xx responses are non-retryable; record will be dead-lettered."
            )

        response.raise_for_status()  # raises HTTPStatusError for 5xx

    def close(self) -> None:
        """Close the underlying httpx client and release connections."""
        self._client.close()

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
