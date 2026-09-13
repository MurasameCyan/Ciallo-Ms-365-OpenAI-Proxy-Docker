"""A write deadline for SSE delivery, and the upstream release that follows it.

WHAT WAS MISSING. `keepalive_stream` already handles the *disconnect* half of this
problem well: it cancels the pending `__anext__` and calls `aclose()` on the
upstream iterator in a `finally`, so a client that goes away releases the
substrate WebSocket. What nothing bounded was the opposite failure -- a client
that stays connected but stops *reading*.

WHY A DEADLINE INSIDE THE GENERATOR CANNOT WORK. Starlette's
`StreamingResponse.stream_response` does one `await send(...)` per chunk, and our
generator is suspended at its `yield` for the whole duration of that await. So
when the client's TCP receive window fills and `send` never returns, the
generator is not running and cannot time itself out; `asyncio.wait_for` around
anything *inside* the generator is looking at the wrong await. The deadline has
to wrap the ASGI `send` callable itself, which is the only thing still executing.

WHAT A STALLED READER COSTS. The turn holds a substrate WebSocket, a slot in the
per-account concurrency gate, and (on the Responses route) the request lock. Left
unbounded, one client that stops reading parks all three until the process
restarts -- upstream's own `_WS_IDLE_TIMEOUT` does not help, because upstream is
not idle: it has data to give and we simply cannot hand it on.

WHY THE TIMEOUT IS PER-WRITE, NOT PER-TURN. A long answer legitimately takes
minutes, so a whole-response budget would kill healthy turns. What is never
legitimate is a single 64KB-ish chunk taking a minute to be accepted by a reader
that is still connected; with `keepalive_stream` emitting a heartbeat every 10s,
a working client demonstrates liveness far more often than the deadline requires.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from typing import Any

from fastapi.responses import StreamingResponse

_log = logging.getLogger("copilot_proxy")

# One accepted write. Generous on purpose: this is a "the reader is gone or wedged"
# threshold, not a performance target. The keepalive interval is 10s, so a healthy
# client proves it is reading at least six times inside this window.
WRITE_DEADLINE_SECONDS = 60.0


class ClientWriteTimeout(Exception):
    """A single SSE write was not accepted inside the deadline."""


def deadline_send(
    send: Callable[[MutableMapping[str, Any]], Awaitable[None]],
    *,
    timeout: float = WRITE_DEADLINE_SECONDS,
) -> Callable[[MutableMapping[str, Any]], Awaitable[None]]:
    """Wrap an ASGI ``send`` so no individual write can block forever."""
    limit = max(float(timeout), 0.001)

    async def _send(message: MutableMapping[str, Any]) -> None:
        try:
            await asyncio.wait_for(send(message), timeout=limit)
        except asyncio.TimeoutError as exc:
            raise ClientWriteTimeout(
                f"the client accepted no SSE data for {limit:.0f}s"
            ) from exc

    return _send


class GuardedStreamingResponse(StreamingResponse):
    """`StreamingResponse` that abandons a reader which has stopped reading.

    Two guarantees, both of which exist because the alternative was measured to
    leak an upstream WebSocket:

    * every ASGI write is bounded by ``write_timeout``;
    * successful delivery is recorded only after the terminal body write;
    * the body iterator is `aclose()`d on every exit path. That close runs
      `keepalive_stream`'s own `finally`, cancels the pending upstream read, and
      releases the substrate connection.

    A timeout is swallowed rather than re-raised: the response is already
    partially written, so there is no status code left to change and nothing a
    500 could tell a client that has stopped listening. It is logged, because a
    silently truncated stream would otherwise be indistinguishable from a
    complete one.
    """

    def __init__(
        self,
        content: AsyncIterator[str],
        *,
        write_timeout: float = WRITE_DEADLINE_SECONDS,
        on_abandon: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(content, **kwargs)
        self._write_timeout = write_timeout
        self._on_abandon = on_abandon
        self.transport_complete = False

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        guarded_send = deadline_send(send, timeout=self._write_timeout)

        async def tracked_send(message) -> None:  # noqa: ANN001
            await guarded_send(message)
            if (
                message.get("type") == "http.response.body"
                and not message.get("more_body", False)
            ):
                self.transport_complete = True

        try:
            await super().__call__(scope, receive, tracked_send)
        except ClientWriteTimeout as exc:
            _log.warning("SSE stream abandoned: %s", exc)
            if self._on_abandon is not None:
                with contextlib.suppress(Exception):
                    self._on_abandon(str(exc))
        finally:
            close = getattr(self.body_iterator, "aclose", None)
            if close is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await close()
