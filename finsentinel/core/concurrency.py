
"""Per-process concurrent-ingestion cap backed by a threading.BoundedSemaphore.

IMPORTANT: this limit is per-process only.  It is NOT shared across multiple
worker processes (e.g. uvicorn --workers N or gunicorn).  Each worker maintains
its own semaphore.  For a shared, cluster-wide rate limit, use a reverse proxy
(e.g. nginx limit_req) or an external token-bucket service.
"""

import threading
from collections.abc import Generator
from contextlib import contextmanager


class IngestionCapacityError(Exception):
    """Raised when no ingestion slot is available (server at per-process capacity)."""


_state_lock = threading.Lock()
_semaphore: threading.BoundedSemaphore | None = None
_cap: int | None = None


def configure_ingestion_cap(max_concurrent: int | None) -> None:
    """Set or clear the per-process concurrent-ingestion cap.

    Pass None to disable the cap (unlimited concurrent ingestion operations).
    Pass a positive integer to enforce a per-process limit.

    Not safe to call while requests are in-flight; slots held before the call
    will never be released against the new semaphore.  Call once at startup.
    """
    global _semaphore, _cap
    with _state_lock:
        if max_concurrent is None:
            _semaphore = None
            _cap = None
            return
        if not isinstance(max_concurrent, int) or max_concurrent <= 0:
            raise ValueError(
                f"max_concurrent must be a positive integer, got {max_concurrent!r}"
            )
        _semaphore = threading.BoundedSemaphore(max_concurrent)
        _cap = max_concurrent


def get_ingestion_cap() -> int | None:
    """Return the configured per-process ingestion cap, or None if unlimited."""
    return _cap


def _get_semaphore() -> threading.BoundedSemaphore | None:
    """Return the live semaphore reference; None if no cap is configured.

    For use by IngestionConcurrencyMiddleware only.  Captures the reference at
    call time so the middleware can release the same semaphore it acquired even
    if configure_ingestion_cap() is called on another thread between acquire
    and release (documented as unsafe mid-flight but recoverable here).
    """
    return _semaphore


@contextmanager
def ingestion_slot() -> Generator[None, None, None]:
    """Acquire one ingestion slot; raise IngestionCapacityError if at capacity.

    Releases the slot on exit whether the body succeeds or raises.
    If no cap is configured this is a no-op (zero overhead).
    """
    s = _semaphore
    if s is None:
        yield
        return

    acquired = s.acquire(blocking=False)
    if not acquired:
        raise IngestionCapacityError(
            "Server is at maximum concurrent ingestion capacity. Try again later."
        )
    try:
        yield
    finally:
        s.release()
