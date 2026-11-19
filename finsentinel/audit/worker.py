"""Background delivery worker for the transactional audit-event outbox.

Runs as a daemon thread started by the FastAPI application lifespan.
Calls ``deliver_pending_events()`` in a loop, sleeping between iterations.

Deployment notes
----------------
- **Per-process**: each uvicorn worker process starts its own delivery thread.
  ``SELECT FOR UPDATE SKIP LOCKED`` in the claim query prevents two threads
  (or two processes) from claiming the same record simultaneously.
- **No delivery_fn configured**: the worker starts but does not mark records
  delivered.  Records remain pending indefinitely.  Set
  ``FINSENTINEL_AUDIT_WEBHOOK_URL`` to enable actual delivery.
- **Backoff**: failed deliveries back off exponentially (see
  ``release_claim_with_backoff`` in ``audit.outbox``).  Dead-lettered records
  require manual investigation.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from audit.outbox import dead_letter_count, deliver_pending_events

logger = logging.getLogger(__name__)

_DEFAULT_IDLE_SLEEP_SECONDS: float = 60.0
_DEFAULT_ACTIVE_SLEEP_SECONDS: float = 1.0


class OutboxDeliveryWorker:
    """Daemon thread that periodically delivers pending outbox records.

    Sleeps ``active_sleep_seconds`` between batches when records were found,
    ``idle_sleep_seconds`` otherwise, so the worker is responsive under load
    but quiet when the outbox is empty.

    Parameters
    ----------
    delivery_fn:
        Called with each event payload dict.  Raising any exception triggers
        backoff and eventual dead-lettering.  Pass ``None`` to disable actual
        delivery (records are retained as pending).
    idle_sleep_seconds:
        Sleep duration between batches when no records were found.
    active_sleep_seconds:
        Sleep duration between batches when records were processed.
    max_events_per_batch:
        ``max_events`` passed to ``deliver_pending_events``.
    """

    def __init__(
        self,
        *,
        delivery_fn: Callable[[dict[str, Any]], None] | None = None,
        idle_sleep_seconds: float = _DEFAULT_IDLE_SLEEP_SECONDS,
        active_sleep_seconds: float = _DEFAULT_ACTIVE_SLEEP_SECONDS,
        max_events_per_batch: int = 50,
    ) -> None:
        self._delivery_fn = delivery_fn
        self._idle_sleep = idle_sleep_seconds
        self._active_sleep = active_sleep_seconds
        self._max_events = max_events_per_batch
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the delivery thread.  No-op if already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="outbox-delivery-worker",
            daemon=True,
        )
        self._thread.start()
        if self._delivery_fn is None:
            logger.warning(
                "Outbox delivery worker started with no delivery_fn. "
                "Pending events will not be forwarded externally. "
                "Configure FINSENTINEL_AUDIT_WEBHOOK_URL to enable delivery."
            )
        else:
            logger.info("Outbox delivery worker started.")

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the thread to stop and wait up to ``timeout`` seconds."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(
                    "Outbox delivery worker did not stop within %.1f s.", timeout
                )
        self._thread = None
        logger.info("Outbox delivery worker stopped.")

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        logger.info("Outbox delivery worker loop started.")
        while not self._stop_event.is_set():
            try:
                result = deliver_pending_events(
                    max_events=self._max_events,
                    delivery_fn=self._delivery_fn,
                )
                if result["claimed"] > 0:
                    logger.info(
                        "Outbox batch: claimed=%d delivered=%d released=%d dead_lettered=%d",
                        result["claimed"],
                        result["delivered"],
                        result["released"],
                        result.get("dead_lettered", 0),
                    )
                    sleep = self._active_sleep
                else:
                    sleep = self._idle_sleep
                    try:
                        _dl = dead_letter_count()
                        if _dl > 0:
                            logger.error(
                                "Dead-lettered audit events: %d record(s) require manual "
                                "investigation (MAX_DELIVERY_ATTEMPTS exceeded).",
                                _dl,
                            )
                    except Exception:
                        logger.warning(
                            "Could not query dead-letter count; skipping check."
                        )
            except Exception:
                logger.exception(
                    "Outbox delivery worker encountered an unexpected error; "
                    "sleeping %.1f s before retrying.",
                    self._idle_sleep,
                )
                sleep = self._idle_sleep
            self._stop_event.wait(timeout=sleep)
        logger.info("Outbox delivery worker loop finished.")
