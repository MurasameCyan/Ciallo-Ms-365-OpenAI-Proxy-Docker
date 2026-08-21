from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable


DEFAULT_KEEPALIVE_SECONDS = 10.0
SSE_KEEPALIVE_COMMENT = ": keepalive\n\n"
ANTHROPIC_PING = f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


async def keepalive_stream(
    stream: AsyncIterator[str],
    *,
    interval: float = DEFAULT_KEEPALIVE_SECONDS,
    heartbeat: str | Callable[[], str] = SSE_KEEPALIVE_COMMENT,
) -> AsyncIterator[str]:
    """Yield an SSE heartbeat while an upstream async iterator is idle.

    The pending ``__anext__`` task is cancelled and awaited when the client
    disconnects, and the upstream iterator is closed if it exposes ``aclose``.
    """
    iterator = stream.__aiter__()
    pending: asyncio.Future | None = asyncio.ensure_future(iterator.__anext__())
    timeout = max(float(interval), 0.001)
    try:
        while pending is not None:
            done, _ = await asyncio.wait({pending}, timeout=timeout)
            if not done:
                yield heartbeat() if callable(heartbeat) else heartbeat
                continue
            try:
                item = pending.result()
            except StopAsyncIteration:
                break
            pending = asyncio.ensure_future(iterator.__anext__())
            yield item
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
        if pending is not None:
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                await pending
        close = getattr(iterator, "aclose", None)
        if close is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await close()


def merge_sse_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(SSE_HEADERS)
    if extra:
        headers.update(extra)
    return headers
