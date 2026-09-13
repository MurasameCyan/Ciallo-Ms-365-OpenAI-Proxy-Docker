"""The SSE write deadline, and the upstream release it guarantees.

The failure being pinned is a client that stays CONNECTED but stops READING. That
is not a disconnect, so `keepalive_stream`'s disconnect handling never fires, and
it is not an upstream idle either -- substrate has data to give. The turn simply
parks on `await send(...)` forever, holding a WebSocket and a concurrency slot.

Every test here drives the real ASGI contract (`http.response.start`, then
`http.response.body` messages) rather than a mock of it, because the whole point
is *where* the await happens: our generator is suspended at its `yield` while
Starlette blocks in `send`, which is why the deadline has to wrap `send` and not
anything inside the generator.
"""

from __future__ import annotations

import asyncio

import pytest

from m365_copilot_openai_proxy.stream_guard import (
    ClientWriteTimeout,
    GuardedStreamingResponse,
    deadline_send,
)


async def _drain(response, *, receive=None):
    """Run one ASGI response to completion, collecting what it sent."""
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def _receive():
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    await response({"type": "http", "asgi": {"spec_version": "2.4"}},
                   receive or _receive, send)
    return sent


def _body_text(sent: list[dict]) -> str:
    return b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()


# ------------------------------------------------------------- deadline_send

def test_a_write_the_client_never_accepts_raises_rather_than_hanging():
    async def check():
        async def stalled(message):
            if message["type"] == "http.response.body":
                await asyncio.sleep(3600)

        guarded = deadline_send(stalled, timeout=0.05)
        with pytest.raises(ClientWriteTimeout):
            # Bounded on purpose: the stalled sender parks for an hour, so if the
            # deadline is ever removed this must FAIL here rather than hang the
            # whole suite. A TimeoutError is not a ClientWriteTimeout, so
            # pytest.raises reports it as the failure it is.
            await asyncio.wait_for(
                guarded({"type": "http.response.body", "body": b"x"}), timeout=2
            )

    asyncio.run(check())


def test_a_header_write_the_client_never_accepts_raises_rather_than_hanging():
    async def check():
        async def stalled(_message):
            await asyncio.sleep(3600)

        guarded = deadline_send(stalled, timeout=0.05)
        with pytest.raises(ClientWriteTimeout):
            await asyncio.wait_for(
                guarded({"type": "http.response.start", "status": 200, "headers": []}),
                timeout=2,
            )

    asyncio.run(check())




def test_a_reader_that_keeps_up_is_untouched():
    async def check():
        seen: list[bytes] = []

        async def fast(message):
            if message["type"] == "http.response.body":
                seen.append(message["body"])

        guarded = deadline_send(fast, timeout=1.0)
        for chunk in (b"a", b"b", b"c"):
            await guarded({"type": "http.response.body", "body": chunk})
        assert seen == [b"a", b"b", b"c"]

    asyncio.run(check())


# ------------------------------------------------- GuardedStreamingResponse

class _TrackedStream:
    """An upstream stream that records whether it was closed.

    This stands in for `keepalive_stream`, whose `aclose` is what cancels the
    pending substrate read -- so "was this closed?" is exactly "was the upstream
    WebSocket released?".
    """

    def __init__(self, chunks, *, hang_after=None):
        self._chunks = list(chunks)
        self._hang_after = hang_after
        self.closed = False
        self.yielded = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._hang_after is not None and self.yielded >= self._hang_after:
            await asyncio.sleep(3600)
        if not self._chunks:
            raise StopAsyncIteration
        self.yielded += 1
        return self._chunks.pop(0)

    async def aclose(self):
        self.closed = True


def test_a_healthy_stream_delivers_everything_and_still_closes_upstream():
    stream = _TrackedStream(["one", "two"])
    response = GuardedStreamingResponse(stream, media_type="text/event-stream")

    sent = asyncio.run(_drain(response))

    assert _body_text(sent) == "onetwo"
    # Even the happy path must release the upstream connection.
    assert stream.closed is True


def test_a_stalled_reader_is_abandoned_and_upstream_is_released():
    """The measured leak: without this the turn holds a substrate WebSocket and a
    concurrency slot until the process restarts."""
    stream = _TrackedStream(["one", "two", "three"])
    abandoned: list[str] = []
    response = GuardedStreamingResponse(
        stream,
        media_type="text/event-stream",
        write_timeout=0.05,
        on_abandon=abandoned.append,
    )

    async def check():
        started = asyncio.get_event_loop().time()

        async def send(message):
            if message["type"] == "http.response.body":
                await asyncio.sleep(3600)

        async def receive():
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        # Bounded for the same reason as above: without the deadline this call
        # never returns, and a hanging test reports nothing useful.
        await asyncio.wait_for(
            response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send),
            timeout=2,
        )
        return asyncio.get_event_loop().time() - started

    elapsed = asyncio.run(check())

    # It returned instead of parking on the write.
    assert elapsed < 5
    assert stream.closed is True
    assert abandoned and "no SSE data" in abandoned[0]


def test_the_timeout_does_not_propagate_to_the_caller():
    """The response is already partially written by then: there is no status code
    left to change, and a raised exception would surface as an unhandled error in
    the server log for what is really a client-side stall."""
    stream = _TrackedStream(["one"])
    response = GuardedStreamingResponse(
        stream, media_type="text/event-stream", write_timeout=0.05
    )

    async def check():
        async def send(message):
            if message["type"] == "http.response.body":
                await asyncio.sleep(3600)

        async def receive():
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        # Must not raise.
        await asyncio.wait_for(
            response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send),
            timeout=2,
        )

    asyncio.run(check())
    assert stream.closed is True


def test_an_upstream_that_hangs_mid_stream_still_releases_on_client_disconnect():
    """The other direction: the reader is fine, upstream went quiet. The client
    disconnect has to reach `aclose` too, or the same slot leaks."""
    stream = _TrackedStream(["one"], hang_after=1)
    response = GuardedStreamingResponse(stream, media_type="text/event-stream")

    async def check():
        async def send(message):
            return None

        async def receive():
            return {"type": "http.disconnect"}

        with_timeout = asyncio.wait_for(
            response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send),
            timeout=5,
        )
        await with_timeout

    asyncio.run(check())
    assert stream.closed is True
