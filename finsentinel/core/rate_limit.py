"""Per-process, per-IP fixed-window rate limiter for the ingestion endpoint.

IMPORTANT — enforcement boundary
---------------------------------
This limiter is **process-local**.  Each uvicorn worker process maintains its
own counter, so a single client can reach ``requests_per_minute × n_workers``
requests per minute cluster-wide.

For cluster-wide rate limiting configure **nginx** (or another edge proxy):

    limit_req_zone $binary_remote_addr zone=finsentinel_ingest:10m rate=10r/s;
    limit_req zone=finsentinel_ingest burst=20 nodelay;

The application-layer limiter is a defence-in-depth measure, not a substitute
for proxy-level enforcement.

Usage
-----
Call ``configure_rate_limit(n)`` at startup (e.g. from ``app/main.py``).
Call ``check_rate_limit(ip)`` in middleware; it returns ``True`` if the
request should be allowed, ``False`` if the limit is exceeded.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
# ip → (window_start_monotonic, count_in_window)
_windows: dict[str, tuple[float, int]] = {}
_rpm: int | None = None
_window_seconds: float = 60.0

# Maximum number of distinct IPs tracked simultaneously.  When the dict reaches
# this size, expired entries are evicted before inserting a new IP.  If still
# full after eviction (all windows still active), the new IP is allowed through
# without tracking — the process-local limiter is defence-in-depth only;
# nginx limit_req is the primary cluster-wide control.
_MAX_TRACKED_IPS_DEFAULT: int = 65_536
_max_tracked_ips: int = _MAX_TRACKED_IPS_DEFAULT


def configure_rate_limit(
    requests_per_minute: int | None,
    window_seconds: float = 60.0,
    max_tracked_ips: int = _MAX_TRACKED_IPS_DEFAULT,
) -> None:
    """Set the per-IP ingestion rate limit.

    Parameters
    ----------
    requests_per_minute:
        Maximum requests allowed per IP per window.  Pass ``None`` to disable
        rate limiting entirely.
    window_seconds:
        Duration of one fixed window in seconds.  Defaults to 60 (1 minute).
        Settable for tests; not exposed as an env var.
    max_tracked_ips:
        Maximum number of distinct IPs held in the counter dict.  When this
        limit is reached, expired entries are evicted first.  If the dict is
        still full (all windows active), new IPs are allowed through without
        tracking.  Defaults to 65 536.
    """
    global _rpm, _window_seconds, _max_tracked_ips
    if requests_per_minute is not None and requests_per_minute <= 0:
        raise ValueError("requests_per_minute must be positive")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if max_tracked_ips <= 0:
        raise ValueError("max_tracked_ips must be positive")
    with _lock:
        _rpm = requests_per_minute
        _window_seconds = window_seconds
        _max_tracked_ips = max_tracked_ips
        _windows.clear()


def get_rate_limit() -> int | None:
    """Return the configured per-IP requests-per-minute limit, or None."""
    return _rpm


def get_window_dict_size() -> int:
    """Return the current number of tracked IPs.  Thread-safe."""
    with _lock:
        return len(_windows)


def _evict_expired_locked(now: float) -> int:
    """Evict expired window entries.  Must be called under ``_lock``."""
    to_delete = [
        ip for ip, (start, _) in _windows.items()
        if now - start >= _window_seconds
    ]
    for ip in to_delete:
        del _windows[ip]
    return len(to_delete)


def evict_expired_entries() -> int:
    """Thread-safe eviction of expired window entries.  Returns count evicted."""
    with _lock:
        return _evict_expired_locked(time.monotonic())


def check_rate_limit(client_ip: str) -> bool:
    """Return True if the request is within the rate limit, False if exceeded.

    Thread-safe.  Uses a fixed-window counter per IP address.  When the limit
    is ``None`` (not configured), always returns ``True``.

    New IPs are only inserted when the dict is below ``max_tracked_ips``.  On
    reaching the cap, expired entries are evicted first.  If the dict is still
    full after eviction, the request is allowed through without tracking
    (conservative: avoids blocking legitimate new clients).

    Parameters
    ----------
    client_ip:
        The source IP address of the request.  ``IngestionRateLimitMiddleware``
        reads this from ``scope["client"]`` — the ASGI server's TCP peer
        address.  **When deployed behind a reverse proxy**, ``scope["client"]``
        is the proxy's IP, not the original client IP.  All clients would then
        share one counter, defeating per-IP limiting.  To preserve per-IP
        semantics, configure the proxy to strip ``X-Forwarded-For`` before
        uvicorn sees it, and start uvicorn WITHOUT ``--proxy-headers``.
        Cluster-wide protection should use nginx ``limit_req`` regardless.
    """
    with _lock:
        if _rpm is None:
            return True

        now = time.monotonic()

        # For new IPs only: evict expired entries if at capacity.
        if client_ip not in _windows and len(_windows) >= _max_tracked_ips:
            _evict_expired_locked(now)
            if len(_windows) >= _max_tracked_ips:
                # Dict still full — allow new IP without tracking.
                return True

        window_start, count = _windows.get(client_ip, (now, 0))

        if now - window_start >= _window_seconds:
            # Window expired — start a fresh window.
            _windows[client_ip] = (now, 1)
            return True

        if count >= _rpm:
            return False

        _windows[client_ip] = (window_start, count + 1)
        return True
