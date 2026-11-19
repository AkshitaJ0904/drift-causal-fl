
"""ASGI middleware: request-body size limit and concurrent-ingestion cap."""

import asyncio
import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class RequestBodyLimitMiddleware:
    """Reject HTTP requests whose actual body exceeds a configured limit.

    Two independent protections are provided:

    1. **Size limit** (``max_body_size``): rejects any body whose total byte
       count exceeds the configured threshold, returning HTTP 413.
    2. **Body-read deadline** (``body_read_timeout_seconds``): imposes a
       wall-clock deadline on the entire body-read phase.  If all chunks are
       not received within the deadline, returns HTTP 408.

    **Enforcement boundary for the read deadline**: this deadline covers the
    time between the ASGI server calling this middleware and the last
    ``http.request`` chunk arriving.  When uvicorn is exposed directly to
    clients, this is an end-to-end client-to-application timeout.  When
    deployed behind a reverse proxy that buffers the full request body before
    forwarding (e.g. nginx with ``client_body_buffer_size``), the deadline
    covers only the proxy-to-application transfer — the client-to-proxy leg
    is unaffected.  In that configuration, set ``client_body_timeout`` in
    the proxy to protect the client-to-proxy leg.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_body_size: int = 10_000_000,
        body_read_timeout_seconds: float | None = None,
    ) -> None:
        if max_body_size <= 0:
            raise ValueError("max_body_size must be positive")
        if body_read_timeout_seconds is not None and body_read_timeout_seconds <= 0:
            raise ValueError("body_read_timeout_seconds must be positive when set")

        self.app = app
        self.max_body_size = max_body_size
        self.body_read_timeout_seconds = body_read_timeout_seconds

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = next(
            (
                value.decode("latin-1")
                for name, value in scope.get("headers", [])
                if name.lower() == b"content-length"
            ),
            None,
        )

        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                await self._reject(send, 400, "Invalid Content-Length header")
                return

            if declared_size < 0:
                await self._reject(send, 400, "Invalid Content-Length header")
                return

            if declared_size > self.max_body_size:
                await self._reject(send, 413, "Request body exceeds the size limit")
                return

        # Buffer only up to the configured limit, before calling FastAPI.
        body_parts: list[bytes] = []
        total_size = 0

        # Establish a wall-clock deadline for the entire body-read phase.
        # Uses the event-loop's monotonic clock so sleeping tasks don't skew it.
        loop = asyncio.get_running_loop()
        body_read_deadline: float | None = (
            loop.time() + self.body_read_timeout_seconds
            if self.body_read_timeout_seconds is not None
            else None
        )

        while True:
            if body_read_deadline is not None:
                remaining = body_read_deadline - loop.time()
                if remaining <= 0:
                    await self._reject(send, 408, "Request body read timed out")
                    return
                try:
                    message = await asyncio.wait_for(receive(), timeout=remaining)
                except TimeoutError:
                    await self._reject(send, 408, "Request body read timed out")
                    return
            else:
                message = await receive()

            if message["type"] == "http.disconnect":
                return

            if message["type"] != "http.request":
                continue

            chunk = message.get("body", b"")
            total_size += len(chunk)

            if total_size > self.max_body_size:
                await self._reject(send, 413, "Request body exceeds the size limit")
                return

            body_parts.append(chunk)

            if not message.get("more_body", False):
                break

        body = b"".join(body_parts)
        body_sent = False

        async def replay_body() -> Message:
            nonlocal body_sent

            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }

            return await receive()

        await self.app(scope, replay_body, send)

    @staticmethod
    async def _reject(send: Send, status_code: int, detail: str) -> None:
        body = ('{"detail":"' + detail + '"}').encode("utf-8")

        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            }
        )


class IngestionRateLimitMiddleware:
    """Per-IP, per-process fixed-window rate limiter for POST /updates.

    Enforces the per-IP rate limit configured via
    ``core.rate_limit.configure_rate_limit``.  Returns HTTP 429 when the
    limit is exceeded.

    **Enforcement boundary** — process-local only.  See ``core/rate_limit.py``
    for the full caveat and the recommended nginx ``limit_req`` configuration
    for cluster-wide protection.

    Must be registered AFTER ``IngestionConcurrencyMiddleware`` in
    ``app.add_middleware()`` calls so that it runs BEFORE the concurrency
    check in the request path (Starlette reverse order).  Placing it
    outermost is correct: cheap IP-based checks should fire first.

    Only POST requests whose path ends with "/updates" are gated; all other
    routes pass through unconditionally.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method", "") != "POST"
            or not scope.get("path", "").endswith("/updates")
        ):
            await self.app(scope, receive, send)
            return

        from core.rate_limit import check_rate_limit, get_rate_limit

        if get_rate_limit() is None:
            await self.app(scope, receive, send)
            return

        client_ip = (scope.get("client") or ("", 0))[0]
        if not check_rate_limit(client_ip):
            logger.warning(
                "Ingestion rate limit exceeded: client_ip=%s path=%s",
                client_ip,
                scope.get("path", ""),
            )
            await self._reject(send, 429, "Rate limit exceeded. Try again later.")
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Send, status_code: int, detail: str) -> None:
        body = ('{"detail":"' + detail + '"}').encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"retry-after", b"60"),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            }
        )


class IngestionConcurrencyMiddleware:
    """Reject ingestion POST requests at the ASGI layer when the per-process cap is reached.

    This middleware must be mounted AFTER RequestBodyLimitMiddleware in
    app.add_middleware() calls so that it runs BEFORE body buffering in the
    request path.  Starlette applies middlewares in reverse registration order,
    so the last-registered middleware is the outermost (first to run).

    Acquisition happens before the body is read, so the cap bounds both the
    number of bodies in memory and the number of concurrent CPU/DB operations.
    The slot is released in a finally block after the full response is sent,
    even if the downstream app raises.

    Only POST requests whose path ends with "/updates" are gated; all other
    routes pass through unconditionally so health and approval endpoints are
    unaffected when the ingestion cap is exhausted.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method", "") != "POST"
            or not scope.get("path", "").endswith("/updates")
        ):
            await self.app(scope, receive, send)
            return

        from core.concurrency import _get_semaphore

        s = _get_semaphore()
        if s is None:
            await self.app(scope, receive, send)
            return

        acquired = s.acquire(blocking=False)
        if not acquired:
            client_ip = (scope.get("client") or ("", 0))[0]
            logger.warning(
                "Ingestion concurrency cap reached: client_ip=%s path=%s",
                client_ip,
                scope.get("path", ""),
            )
            await self._reject(send, 503, "Server is at capacity. Try again later.")
            return

        try:
            await self.app(scope, receive, send)
        finally:
            s.release()

    @staticmethod
    async def _reject(send: Send, status_code: int, detail: str) -> None:
        body = ('{"detail":"' + detail + '"}').encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            }
        )
