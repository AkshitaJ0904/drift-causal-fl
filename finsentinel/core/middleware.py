
"""ASGI middleware that limits HTTP request-body size before route parsing."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyLimitMiddleware:
    """Reject HTTP requests whose actual body exceeds a configured limit."""

    def __init__(self, app: ASGIApp, max_body_size: int = 10_000_000) -> None:
        if max_body_size <= 0:
            raise ValueError("max_body_size must be positive")

        self.app = app
        self.max_body_size = max_body_size

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

        while True:
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
