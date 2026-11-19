"""Tests for per-process concurrent-ingestion cap (core/concurrency.py)."""

import asyncio
import base64
import contextlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import ingestion
from core.concurrency import (
    IngestionCapacityError,
    _get_semaphore,
    configure_ingestion_cap,
    get_ingestion_cap,
    ingestion_slot,
)
from core.middleware import IngestionConcurrencyMiddleware, RequestBodyLimitMiddleware
from ingestion.payload import PayloadIntegrityError


@pytest.fixture(autouse=True)
def reset_cap():
    """Ensure global semaphore is cleared before and after every test."""
    configure_ingestion_cap(None)
    yield
    configure_ingestion_cap(None)


# ---------------------------------------------------------------------------
# Unit tests: configure_ingestion_cap and get_ingestion_cap
# ---------------------------------------------------------------------------


def test_cap_is_none_by_default() -> None:
    assert get_ingestion_cap() is None


def test_configure_cap_stores_value() -> None:
    configure_ingestion_cap(5)
    assert get_ingestion_cap() == 5


def test_configure_cap_to_none_clears_value() -> None:
    configure_ingestion_cap(3)
    configure_ingestion_cap(None)
    assert get_ingestion_cap() is None


def test_configure_cap_zero_raises() -> None:
    with pytest.raises(ValueError):
        configure_ingestion_cap(0)


def test_configure_cap_negative_raises() -> None:
    with pytest.raises(ValueError):
        configure_ingestion_cap(-1)


def test_configure_cap_non_integer_raises() -> None:
    with pytest.raises((ValueError, TypeError)):
        configure_ingestion_cap("5")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Unit tests: ingestion_slot context manager
# ---------------------------------------------------------------------------


def test_ingestion_slot_no_cap_is_noop() -> None:
    # Must not raise and must not change cap
    with ingestion_slot():
        pass
    assert get_ingestion_cap() is None


def test_ingestion_slot_acquires_and_releases() -> None:
    configure_ingestion_cap(1)
    with ingestion_slot():
        pass
    # Slot released — can acquire again
    with ingestion_slot():
        pass


def test_ingestion_slot_raises_at_capacity() -> None:
    configure_ingestion_cap(1)
    with ingestion_slot():
        # Semaphore count is 0; second acquire must fail immediately
        with pytest.raises(IngestionCapacityError):
            with ingestion_slot():
                pass
    # After outer slot released, can acquire again
    with ingestion_slot():
        pass


def test_ingestion_slot_released_on_exception() -> None:
    configure_ingestion_cap(1)

    with pytest.raises(ValueError):
        with ingestion_slot():
            raise ValueError("simulated processing failure")

    # Finally block must have released the slot
    with ingestion_slot():
        pass


def test_ingestion_slot_multiple_slots_respected() -> None:
    configure_ingestion_cap(2)
    with ingestion_slot():
        with ingestion_slot():
            # Both slots held — third must fail
            with pytest.raises(IngestionCapacityError):
                with ingestion_slot():
                    pass
    # Both slots released
    with ingestion_slot():
        with ingestion_slot():
            pass


# ---------------------------------------------------------------------------
# API-level tests (FastAPI TestClient + threads)
# ---------------------------------------------------------------------------

_PAYLOAD = b"cap-test-payload"
_REQUEST_DATA = {
    "envelope": {
        "update_id": "cap-test-update-001",
        "client_id": "cap-test-client",
        "model_version": "cnn-v1",
        "round_number": 1,
        "sample_count": 1,
        "payload_sha256": "a" * 64,
        "payload_size_bytes": len(_PAYLOAD),
        "created_at": "2026-10-21T10:00:00Z",
        "signature": "test-signature",
        "signing_key_id": "key-001",
    },
    "payload_base64": base64.b64encode(_PAYLOAD).decode("ascii"),
}


def _make_test_app() -> FastAPI:
    # Mirrors the production middleware stack ordering:
    # RequestBodyLimitMiddleware first (inner), IngestionConcurrencyMiddleware second
    # (outer) so the slot is checked BEFORE body buffering.
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=10_000_000)
    app.add_middleware(IngestionConcurrencyMiddleware)
    app.include_router(ingestion.router, prefix="/api/v1")
    return app


def test_saturation_returns_503(monkeypatch) -> None:
    """With cap=1, a second concurrent request must receive 503 immediately."""
    configure_ingestion_cap(1)
    entered_validation = Event()
    release_validation = Event()
    app = _make_test_app()

    def blocked_validation(*args, **kwargs):
        entered_validation.set()
        if not release_validation.wait(timeout=5):
            raise TimeoutError("Test timed out waiting for release signal")
        return {"ingestion_status": "validated", "approval_status": "pending_approval"}

    monkeypatch.setattr(ingestion, "get_active_model_update_policy", lambda: object())
    monkeypatch.setattr(ingestion, "validate_incoming_update", blocked_validation)

    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                client.post, "/api/v1/updates", json=_REQUEST_DATA
            )
            assert entered_validation.wait(timeout=2), (
                "First request did not reach validation"
            )

            try:
                second_response = client.post("/api/v1/updates", json=_REQUEST_DATA)
                assert second_response.status_code == 503
                assert "capacity" in second_response.json()["detail"].lower()
            finally:
                release_validation.set()

            first_response = first_future.result(timeout=2)
            assert first_response.status_code == 200


def test_slot_released_after_validation_error(monkeypatch) -> None:
    """After validation raises, the slot is released so the next request succeeds."""
    configure_ingestion_cap(1)
    app = _make_test_app()
    call_count = {"n": 0}

    def fail_first_then_succeed(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise PayloadIntegrityError("test: payload corrupted")
        return {"ingestion_status": "validated", "approval_status": "pending_approval"}

    monkeypatch.setattr(ingestion, "get_active_model_update_policy", lambda: object())
    monkeypatch.setattr(ingestion, "validate_incoming_update", fail_first_then_succeed)

    with TestClient(app) as client:
        # First request: validation fails → 422 (not 503 — slot was released by finally)
        resp1 = client.post("/api/v1/updates", json=_REQUEST_DATA)
        assert resp1.status_code == 422

        # Second request: slot is free again → validation succeeds → 200
        resp2 = client.post("/api/v1/updates", json=_REQUEST_DATA)
        assert resp2.status_code == 200


def test_saturation_rejects_before_endpoint_body_parsing(monkeypatch) -> None:
    """Concurrency check fires BEFORE body parsing, not after.

    Proof: a second concurrent request with invalid Base64 returns 503, not 400.
    If the capacity check ran after Base64 decoding (endpoint level), the
    endpoint would decode the invalid payload first and return 400.  Receiving
    503 proves the middleware rejected the request before the body was parsed.
    """
    configure_ingestion_cap(1)
    entered_first = Event()
    release_first = Event()
    app = _make_test_app()

    def block_first(*args, **kwargs):
        entered_first.set()
        if not release_first.wait(timeout=5):
            raise TimeoutError("Test timed out waiting for release signal")
        return {"ingestion_status": "validated", "approval_status": "pending_approval"}

    monkeypatch.setattr(ingestion, "get_active_model_update_policy", lambda: object())
    monkeypatch.setattr(ingestion, "validate_incoming_update", block_first)

    # Payload_base64 value that is not valid Base64; Pydantic accepts it as a
    # str (no b64 validation at schema level), but the endpoint's b64decode would
    # return 400 if it ran. If the middleware rejects first, we get 503.
    invalid_b64_data = {**_REQUEST_DATA, "payload_base64": "!!!NOT_VALID_BASE64!!!"}

    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                client.post, "/api/v1/updates", json=_REQUEST_DATA
            )
            assert entered_first.wait(timeout=2), "First request did not reach validation"

            try:
                second_response = client.post(
                    "/api/v1/updates", json=invalid_b64_data
                )
                assert second_response.status_code == 503, (
                    f"Expected 503 from middleware capacity check, got "
                    f"{second_response.status_code}. The body was parsed before "
                    f"the capacity check — the concurrency gate is at the wrong layer."
                )
            finally:
                release_first.set()

        first_response = first_future.result(timeout=2)
        assert first_response.status_code == 200


def test_no_cap_allows_concurrent_requests(monkeypatch) -> None:
    """When no cap is configured, ingestion_slot is a no-op for all requests."""
    # cap is None (reset by fixture)
    entered_first = Event()
    release_first = Event()
    entered_second = Event()
    app = _make_test_app()
    call_count = {"n": 0}

    def blocking_then_succeed(*args, **kwargs):
        n = call_count["n"]
        call_count["n"] += 1
        if n == 0:
            entered_first.set()
            release_first.wait(timeout=5)
        else:
            entered_second.set()
        return {"ingestion_status": "validated", "approval_status": "pending_approval"}

    monkeypatch.setattr(ingestion, "get_active_model_update_policy", lambda: object())
    monkeypatch.setattr(ingestion, "validate_incoming_update", blocking_then_succeed)

    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                client.post, "/api/v1/updates", json=_REQUEST_DATA
            )
            assert entered_first.wait(timeout=2)

            # Second request must also enter validation (no cap blocking it)
            second_future = executor.submit(
                client.post, "/api/v1/updates", json=_REQUEST_DATA
            )
            assert entered_second.wait(timeout=2), (
                "Second request was blocked despite no cap being configured"
            )

            release_first.set()
            assert first_future.result(timeout=2).status_code == 200
            assert second_future.result(timeout=2).status_code == 200


# ---------------------------------------------------------------------------
# Cancellation slot-release test (pure asyncio)
# ---------------------------------------------------------------------------


def test_slot_released_on_cancellation() -> None:
    """CancelledError propagating out of downstream still releases the slot.

    Ensures the ``finally`` block in ``IngestionConcurrencyMiddleware.__call__``
    executes even when the task is cancelled mid-flight, so the slot is not
    permanently leaked.
    """

    async def _inner() -> None:
        configure_ingestion_cap(1)
        entered = asyncio.Event()

        async def stalling_app(scope, receive, send) -> None:
            entered.set()
            await asyncio.sleep(100)  # will be cancelled here

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/updates",
            "headers": [],
        }
        mw = IngestionConcurrencyMiddleware(stalling_app)
        task = asyncio.create_task(mw(scope, lambda: asyncio.sleep(100), lambda m: None))  # type: ignore[arg-type, return-value]

        await entered.wait()

        s = _get_semaphore()
        assert s is not None
        # Slot is held — a non-blocking acquire must fail.
        assert not s.acquire(blocking=False), "Slot should be held by in-flight task"

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        # finally block must have released the slot.
        assert s.acquire(blocking=False), "Slot not released after cancellation"
        s.release()  # restore semaphore to its pre-test state

    asyncio.run(_inner())


# ---------------------------------------------------------------------------
# Concurrent near-limit payload test
# ---------------------------------------------------------------------------


def test_concurrent_near_limit_body_bounded(monkeypatch) -> None:
    """With cap=1, the second concurrent request is rejected BEFORE its body is buffered.

    Both requests carry a payload near the body-size limit.  The semaphore
    slot is acquired before ``RequestBodyLimitMiddleware`` buffers the body,
    so only one near-limit body ever occupies memory at a time.

    Proof: the second request receives 503 (capacity, from the middleware),
    not 413 (body-too-large, from the downstream endpoint body-buffering path).
    """
    configure_ingestion_cap(1)
    entered_first = Event()
    release_first = Event()

    # 50 KB body limit; payload is ~37 KB of raw bytes → ~50 KB as base64,
    # so the full JSON sits near but under the limit.  Keeps allocations small.
    _BODY_LIMIT = 50_000
    near_limit_app = FastAPI()
    near_limit_app.add_middleware(RequestBodyLimitMiddleware, max_body_size=_BODY_LIMIT)
    near_limit_app.add_middleware(IngestionConcurrencyMiddleware)
    near_limit_app.include_router(ingestion.router, prefix="/api/v1")

    def block_first(*args, **kwargs):
        entered_first.set()
        if not release_first.wait(timeout=5):
            raise TimeoutError("Test timed out waiting for release signal")
        return {"ingestion_status": "validated", "approval_status": "pending_approval"}

    monkeypatch.setattr(ingestion, "get_active_model_update_policy", lambda: object())
    monkeypatch.setattr(ingestion, "validate_incoming_update", block_first)

    # 37 KB of raw bytes encodes to ~50 KB of base64; full JSON ~50 KB (near limit).
    near_limit_data = {
        **_REQUEST_DATA,
        "payload_base64": base64.b64encode(b"x" * 37_000).decode("ascii"),
    }

    with TestClient(near_limit_app) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                client.post, "/api/v1/updates", json=near_limit_data
            )
            assert entered_first.wait(timeout=2), "First request did not enter validation"

            try:
                second_response = client.post("/api/v1/updates", json=near_limit_data)
                assert second_response.status_code == 503, (
                    f"Expected 503 (capacity gate before body buffering), "
                    f"got {second_response.status_code}. The body was buffered "
                    f"before the slot was checked."
                )
            finally:
                release_first.set()

        first_response = first_future.result(timeout=2)
        assert first_response.status_code == 200
