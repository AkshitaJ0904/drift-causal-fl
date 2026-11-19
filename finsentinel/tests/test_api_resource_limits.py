"""Tests that synchronous update processing does not block ASGI requests."""

import base64
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import ingestion
from core.middleware import RequestBodyLimitMiddleware


def test_blocking_ingestion_does_not_block_health_endpoint(monkeypatch) -> None:
    """CPU and database work in ingestion must run outside the ASGI loop."""
    entered_validation = Event()
    release_validation = Event()
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=10_000_000)
    app.include_router(ingestion.router, prefix="/api/v1")

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    def blocked_validation(*args, **kwargs):
        entered_validation.set()
        if not release_validation.wait(timeout=5):
            raise TimeoutError("Test did not release validation in time.")
        return {"ingestion_status": "validated"}

    monkeypatch.setattr(ingestion, "get_active_model_update_policy", lambda: object())
    monkeypatch.setattr(ingestion, "validate_incoming_update", blocked_validation)

    payload = b"test payload"
    request_data = {
        "envelope": {
            "update_id": "resource-test-update",
            "client_id": "resource-test-client",
            "model_version": "resource-test-model",
            "round_number": 1,
            "sample_count": 1,
            "payload_sha256": "a" * 64,
            "payload_size_bytes": len(payload),
            "created_at": "2026-10-21T10:00:00Z",
            "signature": "test-signature",
            "signing_key_id": "resource-test-key",
        },
        "payload_base64": base64.b64encode(payload).decode("ascii"),
    }

    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            update_future = executor.submit(
                client.post,
                "/api/v1/updates",
                json=request_data,
            )
            assert entered_validation.wait(timeout=2)

            try:
                health_future = executor.submit(client.get, "/api/v1/health")
                health_response = health_future.result(timeout=1)
            finally:
                release_validation.set()

            assert health_response.status_code == 200
            assert update_future.result(timeout=2).status_code == 200
