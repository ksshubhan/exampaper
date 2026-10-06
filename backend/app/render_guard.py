"""A size limit on the render endpoint's request body, applied before parsing.

`/api/render-pdf` is the one route that takes a large, attacker-controlled
string off the wire. Pydantic would happily hold a hundred-megabyte `html`
field in memory while validating it, so the limit cannot live on the model: by
the time a validator runs, the bytes are already here and already parsed.

This is ASGI middleware instead, in front of routing, so an oversized body is
refused on the headers alone — before the JSON is decoded, before the account
is authenticated, and before anything launches a browser.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse

#: Two megabytes, for `html` + `css` + the JSON around them. A real paper's
#: HTML is a few hundred kilobytes, so this is generous; it is not an env var
#: because it is a limit on the shape of our own frontend's output, not
#: something an operator tunes.
MAX_RENDER_BODY_BYTES = 2 * 1024 * 1024

TOO_LARGE_DETAIL = {"code": "render_too_large"}

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def _declared_length(scope: dict[str, Any]) -> int | None:
    """The request's `Content-Length`, or None if absent or unparsable."""
    for name, value in scope.get("headers", ()):
        if name.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _read_capped(
    receive: Receive, limit: int
) -> tuple[list[bytes], bool]:
    """Pull the whole body, stopping the moment it passes `limit`.

    Returns the chunks read and whether the limit was passed. Never holds more
    than one chunk beyond the limit, so a body with no declared length cannot
    be used to fill memory either.
    """
    chunks: list[bytes] = []
    total = 0
    more = True
    while more:
        message = await receive()
        if message["type"] == "http.disconnect":
            return chunks, False
        chunk = message.get("body", b"")
        total += len(chunk)
        if total > limit:
            return chunks, True
        chunks.append(chunk)
        more = bool(message.get("more_body"))
    return chunks, False


def _replay(chunks: list[bytes]) -> Receive:
    """A `receive` that hands back an already-read body, then blocks politely."""
    remaining = list(chunks)

    async def receive() -> dict[str, Any]:
        if remaining:
            return {
                "type": "http.request",
                "body": remaining.pop(0),
                "more_body": bool(remaining),
            }
        return {"type": "http.request", "body": b"", "more_body": False}

    return receive


class RenderBodyLimit:
    """Refuse an oversized POST to `path` with 413, before the app sees it."""

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        path: str,
        max_bytes: int = MAX_RENDER_BODY_BYTES,
    ) -> None:
        self.app = app
        self.path = path
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != self.path
        ):
            await self.app(scope, receive, send)
            return

        declared = _declared_length(scope)
        if declared is not None:
            if declared > self.max_bytes:
                # The cheap path, and the one every real client takes: refused
                # on the header, with not one byte of the body read.
                await self._too_large(scope, receive, send)
                return
            # The server frames the body by this header, so it cannot deliver
            # more than was declared — an in-limit declaration can be trusted,
            # and the request goes through untouched.
            await self.app(scope, receive, send)
            return

        # No declared length (a chunked upload). The size is only knowable by
        # counting, so read it here — where a 413 can still be the whole
        # response — and replay it to the app if it fits.
        chunks, over = await _read_capped(receive, self.max_bytes)
        if over:
            await self._too_large(scope, receive, send)
            return
        await self.app(scope, _replay(chunks), send)

    async def _too_large(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        response = JSONResponse(status_code=413, content={"detail": TOO_LARGE_DETAIL})
        await response(scope, receive, send)
