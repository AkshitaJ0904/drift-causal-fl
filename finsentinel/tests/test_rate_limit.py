"""Tests for the per-process, per-IP ingestion rate limiter.

Coverage:
- configure_rate_limit: validation, None disables limiter
- check_rate_limit: allowed within limit, rejected over limit, window reset,
  per-IP isolation, different clients independent
- IngestionRateLimitMiddleware: 429 on excess, Retry-After header present,
  200 within limit, non-/updates paths unaffected, rate limit unset → pass-through
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import ingestion
from core.concurrency import configure_ingestion_cap
from core.middleware import (
    IngestionConcurrencyMiddleware,
    IngestionRateLimitMiddleware,
    RequestBodyLimitMiddleware,
)
from core.rate_limit import (
    check_rate_limit,
    configure_rate_limit,
    evict_expired_entries,
    get_rate_limit,
    get_window_dict_size,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    configure_rate_limit(None)
    yield
    configure_rate_limit(None)


# ---------------------------------------------------------------------------
# Unit tests: configure_rate_limit / get_rate_limit / check_rate_limit
# ---------------------------------------------------------------------------


def test_rate_limit_none_by_default() -> None:
    assert get_rate_limit() is None


def test_configure_rate_limit_stores_value() -> None:
    configure_rate_limit(10)
    assert get_rate_limit() == 10


def test_configure_rate_limit_to_none_clears_value() -> None:
    configure_rate_limit(5)
    configure_rate_limit(None)
    assert get_rate_limit() is None


def test_configure_rate_limit_zero_raises() -> None:
    with pytest.raises(ValueError):
        configure_rate_limit(0)


def test_configure_rate_limit_negative_raises() -> None:
    with pytest.raises(ValueError):
        configure_rate_limit(-1)


def test_check_rate_limit_no_limit_always_allowed() -> None:
    for _ in range(100):
        assert check_rate_limit("1.2.3.4") is True


def test_check_rate_limit_allows_up_to_limit() -> None:
    configure_rate_limit(5, window_seconds=60)
    for i in range(5):
        assert check_rate_limit("10.0.0.1") is True, f"Request {i + 1} should be allowed"


def test_check_rate_limit_rejects_over_limit() -> None:
    configure_rate_limit(5, window_seconds=60)
    for _ in range(5):
        check_rate_limit("10.0.0.2")
    assert check_rate_limit("10.0.0.2") is False


def test_check_rate_limit_window_reset() -> None:
    configure_rate_limit(2, window_seconds=0.1)
    assert check_rate_limit("10.0.0.3") is True
    assert check_rate_limit("10.0.0.3") is True
    assert check_rate_limit("10.0.0.3") is False  # over limit

    time.sleep(0.15)  # wait for window to expire

    # After window reset, requests are allowed again.
    assert check_rate_limit("10.0.0.3") is True


def test_check_rate_limit_per_ip_isolation() -> None:
    configure_rate_limit(2, window_seconds=60)
    # Exhaust limit for IP A.
    check_rate_limit("192.168.1.1")
    check_rate_limit("192.168.1.1")
    assert check_rate_limit("192.168.1.1") is False

    # IP B has its own counter — still allowed.
    assert check_rate_limit("192.168.1.2") is True


def test_configure_rate_limit_clears_counters() -> None:
    configure_rate_limit(1, window_seconds=60)
    check_rate_limit("10.0.0.4")
    assert check_rate_limit("10.0.0.4") is False

    # Reconfigure — counters must be cleared.
    configure_rate_limit(5, window_seconds=60)
    assert check_rate_limit("10.0.0.4") is True


# ---------------------------------------------------------------------------
# API-level tests (FastAPI TestClient)
# ---------------------------------------------------------------------------


def _make_rate_limited_app(monkeypatch) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=10_000_000)
    app.add_middleware(IngestionConcurrencyMiddleware)
    app.add_middleware(IngestionRateLimitMiddleware)
    app.include_router(ingestion.router, prefix="/api/v1")

    monkeypatch.setattr(ingestion, "get_active_model_update_policy", lambda: object())
    monkeypatch.setattr(
        ingestion,
        "validate_incoming_update",
        lambda *a, **kw: {"ingestion_status": "validated", "approval_status": "pending_approval"},
    )
    return app


_PAYLOAD_DATA = {
    "envelope": {
        "update_id": "rl-test-001",
        "client_id": "rl-client",
        "model_version": "cnn-v1",
        "round_number": 1,
        "sample_count": 1,
        "payload_sha256": "a" * 64,
        "payload_size_bytes": 4,
        "created_at": "2026-10-21T10:00:00Z",
        "signature": "sig",
        "signing_key_id": "key-001",
    },
    "payload_base64": "AAAA",
}


def test_rate_limit_allows_within_limit(monkeypatch) -> None:
    configure_ingestion_cap(None)
    configure_rate_limit(5, window_seconds=60)
    app = _make_rate_limited_app(monkeypatch)

    with TestClient(app) as client:
        for _ in range(5):
            response = client.post("/api/v1/updates", json=_PAYLOAD_DATA)
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"


def test_rate_limit_returns_429_over_limit(monkeypatch) -> None:
    configure_ingestion_cap(None)
    configure_rate_limit(2, window_seconds=60)
    app = _make_rate_limited_app(monkeypatch)

    with TestClient(app) as client:
        client.post("/api/v1/updates", json=_PAYLOAD_DATA)
        client.post("/api/v1/updates", json=_PAYLOAD_DATA)
        response = client.post("/api/v1/updates", json=_PAYLOAD_DATA)
        assert response.status_code == 429
        assert "detail" in response.json()


def test_rate_limit_429_includes_retry_after_header(monkeypatch) -> None:
    configure_ingestion_cap(None)
    configure_rate_limit(1, window_seconds=60)
    app = _make_rate_limited_app(monkeypatch)

    with TestClient(app) as client:
        client.post("/api/v1/updates", json=_PAYLOAD_DATA)
        response = client.post("/api/v1/updates", json=_PAYLOAD_DATA)
        assert response.status_code == 429
        assert "retry-after" in response.headers


def test_rate_limit_does_not_affect_health_endpoint(monkeypatch) -> None:
    configure_rate_limit(1, window_seconds=60)
    from api.health import router as health_router
    app = FastAPI()
    app.add_middleware(IngestionRateLimitMiddleware)
    app.include_router(health_router, prefix="/api/v1")

    with TestClient(app) as client:
        # Health endpoint must pass through even when rate limit is configured.
        for _ in range(10):
            resp = client.get("/api/v1/health")
            assert resp.status_code == 200


def test_rate_limit_not_configured_no_rejection(monkeypatch) -> None:
    configure_ingestion_cap(None)
    # rate limit is None (reset by fixture)
    app = _make_rate_limited_app(monkeypatch)

    with TestClient(app) as client:
        for _ in range(20):
            response = client.post("/api/v1/updates", json=_PAYLOAD_DATA)
            assert response.status_code == 200


def test_rate_limit_fires_before_body_parsing(monkeypatch) -> None:
    """Rate limit check fires BEFORE body is parsed — returns 429, not 422."""
    configure_ingestion_cap(None)
    configure_rate_limit(1, window_seconds=60)
    app = _make_rate_limited_app(monkeypatch)

    invalid_data = {**_PAYLOAD_DATA, "payload_base64": "!!!NOT_BASE64!!!"}

    with TestClient(app) as client:
        client.post("/api/v1/updates", json=_PAYLOAD_DATA)  # exhaust the limit
        # Second request with invalid body should get 429 (rate limit), not 422 (parse error).
        response = client.post("/api/v1/updates", json=invalid_data)
        assert response.status_code == 429, (
            f"Expected 429 from rate limit check before body parsing, got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# Task 4 — Rate-limiter memory protection
# ---------------------------------------------------------------------------


def test_evict_expired_entries_removes_stale_windows() -> None:
    configure_rate_limit(5, window_seconds=0.05)
    check_rate_limit("11.0.0.1")
    check_rate_limit("11.0.0.2")
    assert get_window_dict_size() == 2

    time.sleep(0.1)  # let both windows expire

    evicted = evict_expired_entries()
    assert evicted == 2
    assert get_window_dict_size() == 0


def test_evict_expired_entries_preserves_active_windows() -> None:
    configure_rate_limit(5, window_seconds=10.0)  # long window — won't expire
    check_rate_limit("11.0.1.1")
    assert get_window_dict_size() == 1

    evicted = evict_expired_entries()
    assert evicted == 0, "active window must not be evicted"
    assert get_window_dict_size() == 1, "active window must still be tracked after eviction call"


def test_get_window_dict_size_reflects_actual_size() -> None:
    configure_rate_limit(10, window_seconds=60)
    assert get_window_dict_size() == 0

    for i in range(5):
        check_rate_limit(f"11.0.2.{i}")

    assert get_window_dict_size() == 5


def test_many_ips_bounded_by_max_tracked_ips() -> None:
    cap = 5
    configure_rate_limit(100, window_seconds=0.05, max_tracked_ips=cap)

    # Fill the cap
    for i in range(cap):
        check_rate_limit(f"11.0.3.{i}")
    assert get_window_dict_size() == cap

    time.sleep(0.1)  # let all windows expire

    # New IPs arriving: eviction should clear the expired entries before inserting
    for i in range(cap, cap * 2):
        result = check_rate_limit(f"11.0.3.{i}")
        assert result is True, f"new IP 11.0.3.{i} should be allowed through after eviction"

    # Dict must stay at or below cap
    assert get_window_dict_size() <= cap


def test_rate_limit_enforced_after_eviction() -> None:
    """An IP that was evicted can be re-tracked and rate-limited correctly."""
    cap = 3
    configure_rate_limit(2, window_seconds=0.05, max_tracked_ips=cap)

    # Fill cap with IPs that will expire
    for i in range(cap):
        check_rate_limit(f"11.0.4.{i}")

    time.sleep(0.1)  # let them expire

    # A new IP — eviction runs, it gets tracked fresh
    assert check_rate_limit("11.0.4.99") is True   # count = 1
    assert check_rate_limit("11.0.4.99") is True   # count = 2
    assert check_rate_limit("11.0.4.99") is False  # over limit of 2


# ---------------------------------------------------------------------------
# Task 5 — Proxy and X-Forwarded-For security
# ---------------------------------------------------------------------------


def test_x_forwarded_for_does_not_bypass_rate_limit(monkeypatch) -> None:
    """X-Forwarded-For header must not affect rate-limit counting.

    The middleware reads scope["client"] (the TCP peer address), never
    X-Forwarded-For.  Sending a different XFF header on each request must not
    reset or avoid the per-IP counter.
    """
    configure_ingestion_cap(None)
    configure_rate_limit(1, window_seconds=60)
    app = _make_rate_limited_app(monkeypatch)

    with TestClient(app) as client:
        # First request is within limit — scope["client"] is "testclient"
        r1 = client.post("/api/v1/updates", json=_PAYLOAD_DATA)
        assert r1.status_code == 200

        # Second request with a spoofed XFF claiming a fresh IP — still 429
        # because the limiter ignores the header and uses scope["client"]
        r2 = client.post(
            "/api/v1/updates",
            json=_PAYLOAD_DATA,
            headers={"X-Forwarded-For": "10.99.99.99"},
        )
        assert r2.status_code == 429, (
            "X-Forwarded-For header must not bypass the per-IP rate limit; "
            f"got {r2.status_code} instead of 429"
        )


def test_rate_limit_uses_scope_client_regardless_of_xff(monkeypatch) -> None:
    """All requests from the same TCP peer are counted together, ignoring XFF.

    If the middleware read X-Forwarded-For, requests with different XFF values
    would appear as different IPs and each get a fresh window.  Verifying that
    three requests from the same TestClient connection are all correctly gated
    proves scope["client"] is used exclusively.
    """
    configure_ingestion_cap(None)
    configure_rate_limit(2, window_seconds=60)
    app = _make_rate_limited_app(monkeypatch)

    xff_values = ["192.0.2.1", "192.0.2.2", "192.0.2.3"]

    statuses = []
    with TestClient(app) as client:
        for xff in xff_values:
            resp = client.post(
                "/api/v1/updates",
                json=_PAYLOAD_DATA,
                headers={"X-Forwarded-For": xff},
            )
            statuses.append(resp.status_code)

    # Requests 1 and 2: within limit (200); Request 3: over limit (429)
    assert statuses[0] == 200
    assert statuses[1] == 200
    assert statuses[2] == 429, (
        f"Third request should be rate-limited (429) but got {statuses[2]}; "
        "if each XFF value reset the window, the middleware is reading"
        " X-Forwarded-For instead of scope['client']"
    )
