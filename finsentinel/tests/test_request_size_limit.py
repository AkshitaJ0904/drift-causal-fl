
"""Tests for request-body size enforcement middleware."""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.middleware import RequestBodyLimitMiddleware


def make_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=10)

    @app.post("/")
    async def read_body(request: Request) -> dict[str, int]:
        body = await request.body()
        return {"size": len(body)}

    return app


def test_body_within_limit_is_accepted() -> None:
    client = TestClient(make_test_app())

    response = client.post("/", content=b"1234567890")

    assert response.status_code == 200
    assert response.json() == {"size": 10}


def test_content_length_over_limit_is_rejected() -> None:
    client = TestClient(make_test_app())

    response = client.post("/", content=b"12345678901")

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body exceeds the size limit"


def test_streamed_body_without_content_length_is_rejected() -> None:
    client = TestClient(make_test_app())

    # An iterable body is streamed by HTTPX rather than sent as a fixed body.
    response = client.post(
        "/",
        content=iter([b"123456", b"789012"]),
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body exceeds the size limit"
