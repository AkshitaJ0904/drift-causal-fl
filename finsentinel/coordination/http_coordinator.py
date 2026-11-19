"""HTTP coordinator adapter — queries a live FL coordinator over HTTPS.

This is the production implementation of ``CoordinatorAdapter``.  It makes
synchronous HTTP requests to a coordinator REST API using canonical httpx.

API contract assumed (configure to match your coordinator):
  GET /api/v1/selection?client_id=<id>&round=<n>
       → 200 {"selected": true|false}
       → 404 {"detail": "..."} — client/round unknown
  GET /api/v1/sample_count?client_id=<id>&update_id=<id>&round=<n>
       → 200 {"expected_count": <int>}
       → 404 {"detail": "..."} — unknown

The URL path pattern is configurable via constructor arguments so it can
match different coordinator REST conventions.

Security contract
-----------------
- HTTPS required for non-loopback URLs.  TLS verify always on.
- Bearer token stored once at construction; never logged.
- Returns None on any connectivity or protocol error (graceful degradation).
  Callers that require verified counts must set require_verified=True at the
  sample-count-provider layer, which causes ingestion to fail-closed rather
  than accepting an unverified count.

Thread safety
-------------
httpx.Client is not thread-safe for concurrent requests; each call acquires
a threading.Lock so a single adapter instance can be shared across threads.
"""
from __future__ import annotations

import logging
import threading
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


class CoordinatorConfigError(ValueError):
    """Raised when the adapter cannot be constructed from configuration."""


def _validate_coordinator_url(url: str) -> None:
    if not url or not url.strip():
        raise CoordinatorConfigError("Coordinator URL must not be empty.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise CoordinatorConfigError(
            f"Coordinator URL scheme must be http or https; got {parsed.scheme!r}."
        )
    if parsed.scheme == "http":
        host = (parsed.hostname or "").lower()
        if host not in _LOOPBACK_HOSTS:
            raise CoordinatorConfigError(
                "Coordinator URL uses plain HTTP for a non-loopback host. "
                f"Host {host!r} requires HTTPS."
            )
    if not parsed.netloc:
        raise CoordinatorConfigError("Coordinator URL has no host component.")


class HttpCoordinatorAdapter:
    """Production ``CoordinatorAdapter`` backed by an HTTP coordinator API.

    Parameters
    ----------
    base_url:
        Root URL of the coordinator API, e.g. ``https://coordinator.example.com``.
    token:
        Bearer token sent in the ``Authorization`` header.
    selection_path:
        URL path template for the client-selection endpoint.
        Receives ``client_id`` and ``round_number`` as format kwargs.
        Default: ``/api/v1/selection``  (query params ``client_id`` and ``round``).
    sample_count_path:
        URL path for sample-count lookup.
        Default: ``/api/v1/sample_count``  (query params).
    timeout:
        httpx Timeout for all requests.
    name:
        Human-readable label for logs and audit messages.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        selection_path: str = "/api/v1/selection",
        sample_count_path: str = "/api/v1/sample_count",
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
        name: str = "http-coordinator",
    ) -> None:
        _validate_coordinator_url(base_url)
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._selection_path = selection_path
        self._sample_count_path = sample_count_path
        self._timeout = timeout
        self._lock = threading.Lock()

        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        )

        parsed = urlparse(base_url)
        is_loopback = (parsed.hostname or "").lower() in _LOOPBACK_HOSTS
        if not token and not is_loopback:
            logger.warning(
                "HttpCoordinatorAdapter configured without a token for non-loopback host %r. "
                "Requests to the coordinator will be unauthenticated.",
                parsed.hostname,
            )

    def get_expected_sample_count(
        self,
        *,
        client_id: str,
        update_id: str,
        round_number: int,
    ) -> int | None:
        """Query the coordinator for the expected sample count.

        Returns
        -------
        int
            The coordinator-authoritative expected count.
        None
            When the coordinator has no record, is unreachable, or the
            response cannot be parsed.
        """
        url = self._base_url + self._sample_count_path
        params: dict[str, str | int] = {
            "client_id": client_id,
            "update_id": update_id,
            "round": round_number,
        }
        try:
            with self._lock:
                resp = self._client.get(url, params=params)
        except Exception as exc:
            logger.warning(
                "HttpCoordinatorAdapter.get_expected_sample_count failed for "
                "client_id=%r update_id=%r round=%d: %s",
                client_id, update_id, round_number, exc,
            )
            return None

        if resp.status_code == 404:
            return None

        if resp.status_code != 200:
            logger.warning(
                "Coordinator sample_count endpoint returned HTTP %d for "
                "client_id=%r round=%d.",
                resp.status_code, client_id, round_number,
            )
            return None

        try:
            data: dict[str, Any] = resp.json()
            count = data.get("expected_count")
            if not isinstance(count, int) or count <= 0:
                logger.warning(
                    "Coordinator returned unexpected sample_count payload: %r", data
                )
                return None
            return count
        except Exception as exc:
            logger.warning(
                "Failed to parse coordinator sample_count response: %s", exc
            )
            return None

    def is_client_selected(
        self,
        *,
        client_id: str,
        round_number: int,
    ) -> bool | None:
        """Query the coordinator for client selection status.

        Returns
        -------
        True
            Client was selected for the round.
        False
            Client was explicitly NOT selected.
        None
            Status is unknown (coordinator has no record or is unreachable).
        """
        url = self._base_url + self._selection_path
        params: dict[str, str | int] = {"client_id": client_id, "round": round_number}
        try:
            with self._lock:
                resp = self._client.get(url, params=params)
        except Exception as exc:
            logger.warning(
                "HttpCoordinatorAdapter.is_client_selected failed for "
                "client_id=%r round=%d: %s",
                client_id, round_number, exc,
            )
            return None

        if resp.status_code == 404:
            return None

        if resp.status_code != 200:
            logger.warning(
                "Coordinator selection endpoint returned HTTP %d for "
                "client_id=%r round=%d.",
                resp.status_code, client_id, round_number,
            )
            return None

        try:
            data: dict[str, Any] = resp.json()
            selected = data.get("selected")
            if not isinstance(selected, bool):
                logger.warning(
                    "Coordinator returned unexpected selection payload: %r", data
                )
                return None
            return selected
        except Exception as exc:
            logger.warning(
                "Failed to parse coordinator selection response: %s", exc
            )
            return None

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
