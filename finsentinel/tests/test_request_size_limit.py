
"""Tests for request-body size enforcement middleware."""

import asyncio

import pytest
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


# ---------------------------------------------------------------------------
# Body-read timeout tests (pure asyncio — no TestClient needed)
# ---------------------------------------------------------------------------


def _make_scope() -> dict:
    return {"type": "http", "method": "POST", "path": "/", "headers": []}


def _run_mw(mw: RequestBodyLimitMiddleware, receive, scope=None) -> list[dict]:
    """Drive the middleware with a fake receive; collect every send() message."""
    messages: list[dict] = []

    async def _capture(msg: dict) -> None:
        messages.append(msg)

    async def _inner() -> None:
        async def _app(scope, receive, send) -> None:
            pass  # downstream never reached when timeout fires

        await mw(scope or _make_scope(), receive, _capture)  # type: ignore[arg-type]

    asyncio.run(_inner())
    return messages


def _status_codes(messages: list[dict]) -> list[int]:
    return [m["status"] for m in messages if "status" in m]


def test_body_read_timeout_rejects_slow_receive() -> None:
    """When receive() stalls beyond the deadline, the middleware returns 408."""

    async def slow_receive() -> dict:
        await asyncio.sleep(10)
        return {"type": "http.request", "body": b"data", "more_body": False}

    mw = RequestBodyLimitMiddleware(
        None,  # type: ignore[arg-type]
        max_body_size=10_000_000,
        body_read_timeout_seconds=0.05,
    )
    msgs = _run_mw(mw, slow_receive)
    assert _status_codes(msgs) == [408]


def test_body_read_timeout_allows_fast_body() -> None:
    """A fast body is accepted even when a timeout is configured."""
    received_body: list[bytes] = []

    async def fast_receive() -> dict:
        return {"type": "http.request", "body": b"hello", "more_body": False}

    async def _inner() -> None:
        async def _downstream(scope, receive, send) -> None:
            received_body.append((await receive())["body"])

        mw = RequestBodyLimitMiddleware(
            _downstream,
            max_body_size=10_000_000,
            body_read_timeout_seconds=5.0,
        )
        await mw(_make_scope(), fast_receive, lambda m: None)  # type: ignore[arg-type, return-value]

    asyncio.run(_inner())
    assert received_body == [b"hello"]


def test_body_read_timeout_none_does_not_time_out() -> None:
    """With no timeout configured, a slow receive() is not interrupted."""
    received: list[bool] = []

    async def _inner() -> None:
        call_count = {"n": 0}

        async def two_chunk_receive() -> dict:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"type": "http.request", "body": b"abc", "more_body": True}
            return {"type": "http.request", "body": b"def", "more_body": False}

        async def _downstream(scope, receive, send) -> None:
            body = b""
            while True:
                chunk = await receive()
                body += chunk["body"]
                if not chunk.get("more_body"):
                    break
            received.append(body == b"abcdef")

        mw = RequestBodyLimitMiddleware(
            _downstream,
            max_body_size=10_000_000,
            body_read_timeout_seconds=None,
        )
        await mw(_make_scope(), two_chunk_receive, lambda m: None)  # type: ignore[arg-type, return-value]

    asyncio.run(_inner())
    assert received == [True]


def test_body_read_timeout_invalid_zero_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        RequestBodyLimitMiddleware(None, body_read_timeout_seconds=0)  # type: ignore[arg-type]


def test_body_read_timeout_invalid_negative_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        RequestBodyLimitMiddleware(None, body_read_timeout_seconds=-1.0)  # type: ignore[arg-type]
