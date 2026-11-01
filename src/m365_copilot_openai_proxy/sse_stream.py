from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable


DEFAULT_KEEPALIVE_SECONDS = 10.0
SSE_KEEPALIVE_COMMENT = ": keepalive\n\n"
ANTHROPIC_PING = f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"
_RESPONSES_TERMINAL = frozenset({"response.completed", "response.failed", "response.incomplete"})
SSE_HEADERS = {
    # no-cache permits storage and only forces revalidation; a turn's answer
    # exists once and cannot be revalidated, so storage is refused outright.
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
}


@contextlib.asynccontextmanager
async def closing_stream(stream: AsyncIterator) -> AsyncIterator[AsyncIterator]:
    """Close an owned iterator before its consumer exits, including at a yield."""
    try:
        yield stream
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()


async def keepalive_stream(
    stream: AsyncIterator[str],
    *,
    interval: float = DEFAULT_KEEPALIVE_SECONDS,
    heartbeat: str | Callable[[], str] = SSE_KEEPALIVE_COMMENT,
    observe: Callable[[str], str] | None = None,
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
            yield observe(item) if observe is not None else item
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


class ChatHeartbeat:
    """Empty-delta chunks on the live completion while the upstream is silent.

    An SSE comment keeps the socket open but is not an event, so a client whose
    stall watchdog resets only on data reports a buffered tool turn as stuck and
    re-sends it. Outside a completion (before its first chunk, after its finish)
    the comment stays: there is no live chunk id to extend.
    """

    def __init__(self) -> None:
        self._base: dict | None = None
        self._done = False

    def observe(self, item: str) -> str:
        if self._done:
            return item
        for line in item.split("\n"):
            if not line.startswith("data: "):
                continue
            if line == "data: [DONE]":
                self._done = True
                break
            try:
                chunk = json.loads(line[6:])
            except ValueError:
                continue
            if not isinstance(chunk, dict) or chunk.get("object") != "chat.completion.chunk":
                continue
            if self._base is None:
                self._base = {key: chunk.get(key) for key in ("id", "object", "created", "model")}
            if any(isinstance(choice, dict) and choice.get("finish_reason") is not None for choice in chunk.get("choices") or ()):
                self._done = True
        return item

    def __call__(self) -> str:
        if self._base is None or self._done:
            return SSE_KEEPALIVE_COMMENT
        return f"data: {json.dumps({**self._base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': None}]})}\n\n"


class ResponsesHeartbeat:
    """`keepalive` events numbered into the stream they join.

    Responses events carry `sequence_number`; the official SDK treats
    `{"type": "keepalive"}` as a no-op transport event holding the next number.
    Every later event is shifted by the keepalives already inserted, so the
    numbering stays strictly increasing.
    """

    def __init__(self) -> None:
        self._next = 0
        self._shift = 0
        self._done = False

    def observe(self, item: str) -> str:
        blocks = item.split("\n\n")
        for index, block in enumerate(blocks):
            lines = block.split("\n")
            for position, line in enumerate(lines):
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except ValueError:
                    continue
                sequence = event.get("sequence_number") if isinstance(event, dict) else None
                if not isinstance(sequence, int) or isinstance(sequence, bool):
                    continue
                if self._shift:
                    sequence += self._shift
                    event["sequence_number"] = sequence
                    lines[position] = "data: " + json.dumps(event)
                self._next = sequence + 1
                if event.get("type") in _RESPONSES_TERMINAL:
                    self._done = True
            blocks[index] = "\n".join(lines)
        return "\n\n".join(blocks) if self._shift else item

    def __call__(self) -> str:
        if self._next == 0 or self._done:
            return SSE_KEEPALIVE_COMMENT
        event = {"type": "keepalive", "sequence_number": self._next}
        self._next += 1
        self._shift += 1
        return f"event: keepalive\ndata: {json.dumps(event)}\n\n"


def chat_keepalive_stream(stream: AsyncIterator[str], *, interval: float = DEFAULT_KEEPALIVE_SECONDS) -> AsyncIterator[str]:
    heartbeat = ChatHeartbeat()
    return keepalive_stream(stream, interval=interval, heartbeat=heartbeat, observe=heartbeat.observe)


def responses_keepalive_stream(stream: AsyncIterator[str], *, interval: float = DEFAULT_KEEPALIVE_SECONDS) -> AsyncIterator[str]:
    heartbeat = ResponsesHeartbeat()
    return keepalive_stream(stream, interval=interval, heartbeat=heartbeat, observe=heartbeat.observe)


def merge_sse_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(SSE_HEADERS)
    if extra:
        headers.update(extra)
    return headers
