"""Tests for the /health/metrics operational-metrics endpoint.

Coverage:
- GET /health returns 200 (no auth required)
- GET /health/metrics returns 401 without auth token
- GET /health/metrics returns 503 when token is unconfigured
- GET /health/metrics returns 200 with correct schema when authenticated
- Outbox counts are present in the response
- Rate limit and concurrency cap values reflect configuration
- Outbox backend failure returns 200 with error field (graceful degradation)
- No credentials, tokens, keys, or payloads are present
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.health import router as health_router
from core.concurrency import configure_ingestion_cap
from core.rate_limit import configure_rate_limit

_TEST_TOKEN = "test-operator-token-for-metrics-tests"
_AUTH_HEADER = {"Authorization": f"Bearer {_TEST_TOKEN}"}


@pytest.fixture(autouse=True)
def _reset_configs(monkeypatch):
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", _TEST_TOKEN)
    configure_ingestion_cap(None)
    configure_rate_limit(None)
    yield
    configure_ingestion_cap(None)
    configure_rate_limit(None)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(health_router, prefix="/api/v1")
    return app


# ---------------------------------------------------------------------------
# /health (existing contract must not break)
# ---------------------------------------------------------------------------


def test_health_still_returns_200() -> None:
    with TestClient(_make_app()) as client:
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# /health/metrics — schema
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# /health/metrics — authentication requirement
# ---------------------------------------------------------------------------


def test_metrics_returns_401_without_auth() -> None:
    with TestClient(_make_app()) as client:
        resp = client.get("/api/v1/health/metrics")
    assert resp.status_code == 401


def test_metrics_returns_503_when_token_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("FINSENTINEL_OPERATOR_TOKEN", raising=False)
    with TestClient(_make_app()) as client:
        resp = client.get("/api/v1/health/metrics")
    assert resp.status_code == 503


def test_metrics_returns_401_with_wrong_token() -> None:
    with TestClient(_make_app()) as client:
        resp = client.get("/api/v1/health/metrics", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_metrics_returns_200() -> None:
    with TestClient(_make_app()) as client:
        resp = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER)
    assert resp.status_code == 200


def test_metrics_has_required_top_level_keys() -> None:
    with TestClient(_make_app()) as client:
        body = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER).json()
    assert "outbox" in body
    assert "ingestion" in body
    assert "rate_limit" in body


def test_metrics_outbox_has_expected_keys() -> None:
    with TestClient(_make_app()) as client:
        body = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER).json()
    outbox = body["outbox"]
    assert "pending_count" in outbox
    assert "dead_letter_count" in outbox
    assert "error" in outbox


def test_metrics_ingestion_has_expected_keys() -> None:
    with TestClient(_make_app()) as client:
        body = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER).json()
    ingestion = body["ingestion"]
    assert "concurrency_cap" in ingestion
    assert "concurrency_cap_scope" in ingestion


def test_metrics_rate_limit_has_expected_keys() -> None:
    with TestClient(_make_app()) as client:
        body = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER).json()
    rl = body["rate_limit"]
    assert "requests_per_minute" in rl
    assert "scope" in rl
    assert "note" in rl


# ---------------------------------------------------------------------------
# /health/metrics — reflects configuration
# ---------------------------------------------------------------------------


def test_metrics_rate_limit_none_when_not_configured() -> None:
    with TestClient(_make_app()) as client:
        body = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER).json()
    assert body["rate_limit"]["requests_per_minute"] is None
    assert body["rate_limit"]["scope"] is None


def test_metrics_rate_limit_reports_configured_value() -> None:
    configure_rate_limit(30)
    with TestClient(_make_app()) as client:
        body = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER).json()
    assert body["rate_limit"]["requests_per_minute"] == 30
    assert body["rate_limit"]["scope"] == "process-local"


def test_metrics_concurrency_cap_none_when_not_configured() -> None:
    with TestClient(_make_app()) as client:
        body = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER).json()
    assert body["ingestion"]["concurrency_cap"] is None
    assert body["ingestion"]["concurrency_cap_scope"] is None


def test_metrics_concurrency_cap_reports_configured_value() -> None:
    configure_ingestion_cap(5)
    with TestClient(_make_app()) as client:
        body = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER).json()
    assert body["ingestion"]["concurrency_cap"] == 5
    assert body["ingestion"]["concurrency_cap_scope"] == "process-local"


# ---------------------------------------------------------------------------
# /health/metrics — outbox counts (SQLite test db via conftest)
# ---------------------------------------------------------------------------


def test_metrics_outbox_counts_are_integers_or_none() -> None:
    with TestClient(_make_app()) as client:
        body = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER).json()
    outbox = body["outbox"]
    # With the SQLite test db configured, counts should be integers (≥ 0)
    assert outbox["error"] is None
    assert isinstance(outbox["pending_count"], int)
    assert isinstance(outbox["dead_letter_count"], int)
    assert outbox["pending_count"] >= 0
    assert outbox["dead_letter_count"] >= 0


# ---------------------------------------------------------------------------
# /health/metrics — graceful degradation when outbox is unavailable
# ---------------------------------------------------------------------------


def test_metrics_outbox_error_reports_gracefully(monkeypatch) -> None:
    """Outbox backend failure returns 200 with error field set."""
    import audit.outbox as outbox_mod

    def _boom():
        raise RuntimeError("DB unavailable")

    monkeypatch.setattr(outbox_mod, "pending_count", _boom)
    monkeypatch.setattr(outbox_mod, "dead_letter_count", _boom)

    with TestClient(_make_app()) as client:
        resp = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER)

    assert resp.status_code == 200
    outbox = resp.json()["outbox"]
    assert outbox["pending_count"] is None
    assert outbox["dead_letter_count"] is None
    assert outbox["error"] is not None


# ---------------------------------------------------------------------------
# Security: metrics must not expose sensitive values
# ---------------------------------------------------------------------------


def test_metrics_does_not_expose_tokens(monkeypatch) -> None:
    """Response body must contain no credential-like strings."""
    monkeypatch.setenv("FINSENTINEL_OPERATOR_TOKEN", _TEST_TOKEN)
    with TestClient(_make_app()) as client:
        resp = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER)
    assert _TEST_TOKEN not in resp.text


def test_metrics_does_not_expose_db_password(monkeypatch) -> None:
    monkeypatch.setenv("DB_PASSWORD", "hunter2")
    with TestClient(_make_app()) as client:
        resp = client.get("/api/v1/health/metrics", headers=_AUTH_HEADER)
    assert "hunter2" not in resp.text
