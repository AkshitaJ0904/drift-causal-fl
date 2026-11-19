"""Tests for OutboxDeliveryWorker lifecycle and delivery-failure retry semantics.

Tasks covered
-------------
Task 1 — Worker lifecycle: start/stop, thread-safety, exception resilience,
         FastAPI lifespan integration, test-suite isolation.
Task 2 — At-least-once delivery: delivery_fn succeeds, mark_delivered fails →
         worker retries with the same idempotency_key.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from audit.worker import OutboxDeliveryWorker

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FAST_IDLE = 0.05
_FAST_ACTIVE = 0.01
_EMPTY_RESULT = {"claimed": 0, "delivered": 0, "released": 0, "dead_lettered": 0}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fast_worker(**overrides) -> OutboxDeliveryWorker:
    """Create a test worker with sub-second sleep intervals."""
    return OutboxDeliveryWorker(
        delivery_fn=overrides.pop("delivery_fn", None),
        idle_sleep_seconds=overrides.pop("idle_sleep_seconds", _FAST_IDLE),
        active_sleep_seconds=overrides.pop("active_sleep_seconds", _FAST_ACTIVE),
        **overrides,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_outbox():
    """Truncate the outbox table before/after each test to prevent cross-test bleed."""
    from sqlalchemy import delete

    from core.supabase.session import SessionLocal
    from db.models.audit_outbox import AuditOutboxRecord

    def _truncate() -> None:
        with SessionLocal() as db:
            with db.begin():
                db.execute(delete(AuditOutboxRecord))

    _truncate()
    yield
    _truncate()


# ---------------------------------------------------------------------------
# Task 1 — Worker lifecycle
# ---------------------------------------------------------------------------


def test_worker_starts_successfully():
    with patch("audit.worker.deliver_pending_events", return_value=_EMPTY_RESULT):
        w = _fast_worker()
        w.start()
        assert w.is_alive
        w.stop(timeout=2.0)
        assert not w.is_alive


def test_repeated_start_no_duplicate_threads():
    """A second start() while the thread is alive must be a no-op."""
    with patch("audit.worker.deliver_pending_events", return_value=_EMPTY_RESULT):
        w = _fast_worker()
        w.start()
        thread_first = w._thread
        w.start()  # idempotent call
        thread_second = w._thread
        w.stop(timeout=2.0)

    assert thread_first is thread_second, "start() spawned a second thread"


def test_worker_stops_gracefully():
    """stop() joins the thread and sets is_alive to False."""
    first_call = threading.Event()

    def _deliver(**_kw):
        first_call.set()
        return _EMPTY_RESULT

    with patch("audit.worker.deliver_pending_events", side_effect=_deliver):
        w = _fast_worker()
        w.start()
        assert first_call.wait(timeout=2.0), "worker never ran deliver_pending_events"
        w.stop(timeout=2.0)

    assert not w.is_alive


def test_stop_during_idle_sleep_wakes_promptly():
    """stop() must interrupt a long idle sleep and return in well under 1 s."""
    with patch("audit.worker.deliver_pending_events", return_value=_EMPTY_RESULT):
        # 30 s idle — far longer than any test run
        w = OutboxDeliveryWorker(idle_sleep_seconds=30.0, active_sleep_seconds=0.01)
        w.start()
        time.sleep(0.1)  # let the first loop finish and enter idle sleep

        t0 = time.monotonic()
        w.stop(timeout=3.0)
        elapsed = time.monotonic() - t0

    assert not w.is_alive
    assert elapsed < 1.0, (
        f"stop() took {elapsed:.3f}s — idle sleep was not interrupted by _stop_event"
    )


def test_stop_during_delivery_bounded_shutdown():
    """stop() must return within its timeout even if deliver_pending_events is blocking."""
    delivery_started = threading.Event()
    allow_finish = threading.Event()

    def _slow(**_kw):
        delivery_started.set()
        allow_finish.wait(timeout=10.0)
        return _EMPTY_RESULT

    with patch("audit.worker.deliver_pending_events", side_effect=_slow):
        w = _fast_worker(idle_sleep_seconds=0.01)
        w.start()
        assert delivery_started.wait(timeout=2.0), "worker did not start delivering"

        allow_finish.set()  # unblock delivery so thread can exit cleanly
        t0 = time.monotonic()
        w.stop(timeout=3.0)
        elapsed = time.monotonic() - t0

    assert elapsed < 3.5, f"stop() blocked for {elapsed:.2f}s — exceeded timeout"


def test_worker_exits_within_bounded_period():
    """Worker exits within 1 s when delivery is instantaneous."""
    with patch("audit.worker.deliver_pending_events", return_value=_EMPTY_RESULT):
        w = _fast_worker()
        w.start()
        t0 = time.monotonic()
        w.stop(timeout=1.0)
        elapsed = time.monotonic() - t0

    assert not w.is_alive
    assert elapsed < 1.5, f"Worker did not exit within bounded period ({elapsed:.2f}s)"


def test_delivery_exception_does_not_kill_worker():
    """An exception inside deliver_pending_events must not terminate the worker thread."""
    second_call = threading.Event()
    call_index = {"n": 0}

    def _fail_once(**_kw):
        call_index["n"] += 1
        if call_index["n"] == 1:
            raise RuntimeError("simulated delivery crash")
        second_call.set()
        return _EMPTY_RESULT

    with patch("audit.worker.deliver_pending_events", side_effect=_fail_once):
        w = _fast_worker(idle_sleep_seconds=0.02)
        w.start()
        reached_second = second_call.wait(timeout=3.0)
        still_alive = w.is_alive
        w.stop(timeout=2.0)

    assert reached_second, "worker never reached the second iteration after an exception"
    assert still_alive, "worker thread died after a single deliver_pending_events exception"


def test_fastapi_lifespan_starts_worker_when_enabled(monkeypatch):
    """_lifespan starts (and later stops) the worker when the env-var is truthy."""
    monkeypatch.setenv("FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED", "1")

    from app.main import _lifespan  # noqa: PLC0415
    from app.main import app as _app  # noqa: PLC0415

    with patch("audit.worker.OutboxDeliveryWorker") as MockWorker:
        mock_instance = MockWorker.return_value

        async def _run() -> None:
            async with _lifespan(_app):
                pass  # lifespan entered and exited

        asyncio.run(_run())

    MockWorker.assert_called_once()
    mock_instance.start.assert_called_once()
    mock_instance.stop.assert_called_once()


def test_fastapi_lifespan_does_not_start_worker_when_disabled(monkeypatch):
    """_lifespan must not create a worker when the env-var is absent."""
    monkeypatch.delenv("FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED", raising=False)

    from app.main import _lifespan  # noqa: PLC0415
    from app.main import app as _app  # noqa: PLC0415

    with patch("audit.worker.OutboxDeliveryWorker") as MockWorker:
        async def _run() -> None:
            async with _lifespan(_app):
                pass

        asyncio.run(_run())

    MockWorker.assert_not_called()


def test_worker_disabled_in_tests_by_default():
    """Confirm the worker env-var is not set in the test suite."""
    val = os.environ.get("FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED", "").strip().lower()
    assert val not in ("1", "true", "yes"), (
        "FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED is truthy in the test environment; "
        "this would start live background threads and break test isolation."
    )


# ---------------------------------------------------------------------------
# Task 2 — At-least-once delivery + idempotency_key stability
# ---------------------------------------------------------------------------


def test_delivery_succeeds_mark_delivered_fails_record_retried():
    """If mark_delivered raises after a successful external delivery, the record is
    released via release_claim_with_backoff and the idempotency_key is preserved."""
    import audit.outbox as _outbox  # noqa: PLC0415
    from audit.outbox import deliver_pending_events, enqueue  # noqa: PLC0415
    from core.supabase.session import SessionLocal  # noqa: PLC0415
    from db.models.audit_outbox import AuditOutboxRecord  # noqa: PLC0415

    # Stage a pending outbox record
    with SessionLocal() as db:
        with db.begin():
            rec = enqueue(
                db,
                event_id=None,
                event_type="test.retry",
                severity="low",
                description="at-least-once retry test",
                client_id="cl-retry",
                update_id="u-retry",
            )
            db.flush()
            record_id = rec.id
            original_key = rec.idempotency_key

    delivered_keys: list[str] = []

    def _delivery_fn(payload: dict[str, Any]) -> None:
        delivered_keys.append(payload["idempotency_key"])

    # --- First delivery attempt ---
    # delivery_fn succeeds; mark_delivered raises → expect release_claim_with_backoff
    _real_mark = _outbox.mark_delivered
    _fail_toggle = {"done": False}

    def _mark_fail_once(db, record):
        if not _fail_toggle["done"]:
            _fail_toggle["done"] = True
            raise RuntimeError("simulated DB write failure after external delivery")
        _real_mark(db, record)

    with patch.object(_outbox, "mark_delivered", side_effect=_mark_fail_once):
        r1 = deliver_pending_events(delivery_fn=_delivery_fn)

    assert r1["claimed"] == 1
    assert r1["delivered"] == 0, "mark_delivered failed; record should not be counted as delivered"
    assert r1["released"] == 1, "record must be released with backoff when mark_delivered fails"
    assert len(delivered_keys) == 1
    assert delivered_keys[0] == original_key

    # Record must be pending with retry_after set
    with SessionLocal() as db:
        row = db.get(AuditOutboxRecord, record_id)
        assert row is not None
        assert row.status == "pending"
        assert row.retry_after is not None, "retry_after must be set after mark_delivered failure"

    # Clear retry_after so the record is immediately reclaimable in the next call
    with SessionLocal() as db:
        with db.begin():
            row = db.get(AuditOutboxRecord, record_id)
            row.retry_after = None

    # --- Second delivery attempt (retry) ---
    r2 = deliver_pending_events(delivery_fn=_delivery_fn)

    assert r2["claimed"] == 1
    assert r2["delivered"] == 1

    assert len(delivered_keys) == 2, (
        "delivery_fn must be called twice — at-least-once guarantee"
    )
    assert delivered_keys[1] == original_key, (
        f"idempotency_key changed on retry: "
        f"attempt1={delivered_keys[0]!r} attempt2={delivered_keys[1]!r}"
    )


def test_idempotency_key_stable_across_retries():
    """idempotency_key is set once at enqueue and never mutated by retry/backoff."""
    import audit.outbox as _outbox  # noqa: PLC0415
    from audit.outbox import deliver_pending_events, enqueue  # noqa: PLC0415
    from core.supabase.session import SessionLocal  # noqa: PLC0415
    from db.models.audit_outbox import AuditOutboxRecord  # noqa: PLC0415

    with SessionLocal() as db:
        with db.begin():
            rec = enqueue(
                db,
                event_id=None,
                event_type="test.idempotency",
                severity="low",
                description="idempotency key stability",
                client_id="cl-idem",
                update_id="u-idem",
            )
            db.flush()
            record_id = rec.id
            original_key = rec.idempotency_key

    seen_keys: list[str] = []

    def _delivery_fn(payload: dict[str, Any]) -> None:
        seen_keys.append(payload["idempotency_key"])

    _real_mark = _outbox.mark_delivered
    _attempt = {"n": 0}

    def _mark_fail_first(db, record):
        _attempt["n"] += 1
        if _attempt["n"] == 1:
            raise RuntimeError("simulated DB error")
        _real_mark(db, record)

    # Attempt 1: mark_delivered fails
    with patch.object(_outbox, "mark_delivered", side_effect=_mark_fail_first):
        deliver_pending_events(delivery_fn=_delivery_fn)

    # Reset backoff so the record is immediately reclaimable
    with SessionLocal() as db:
        with db.begin():
            row = db.get(AuditOutboxRecord, record_id)
            row.retry_after = None

    # Attempt 2: succeeds
    deliver_pending_events(delivery_fn=_delivery_fn)

    assert len(seen_keys) == 2
    assert seen_keys[0] == original_key, f"Attempt 1 used wrong key: {seen_keys[0]!r}"
    assert seen_keys[1] == original_key, f"Attempt 2 used wrong key: {seen_keys[1]!r}"
    assert seen_keys[0] == seen_keys[1], (
        f"idempotency_key mutated between delivery attempts: {seen_keys}"
    )
