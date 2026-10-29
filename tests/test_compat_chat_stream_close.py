"""Closing a stream must release the turn, not just the wrapper.

``_compat_chat_stream`` exists so a client that does not accept the newer
keyword arguments can still be streamed from. Its first version was a plain
``async for ...: yield``, which made it OWN nothing: the caller's
``closing_stream`` closed the wrapper, and the inner ``chat_stream`` generator
kept the upstream socket, the session lock and the account slot until
whichever loop turn happened to finalise it. ``aclose()`` then returned with
all three still held, so a client that disconnected mid-answer kept the
conversation blocked.
"""

from __future__ import annotations

import asyncio

from m365_copilot_openai_proxy.response_helpers import _compat_chat_stream
from m365_copilot_openai_proxy.sse_stream import closing_stream


class _RecordingStreamClient:
    """Streams ``chunks`` and records whether it was closed, and when."""

    def __init__(self, chunks: list[str], *, close_event: asyncio.Event | None = None):
        self.chunks = chunks
        self.closed = False
        self.close_event = close_event

    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        try:
            for chunk in self.chunks:
                yield chunk
        finally:
            self.closed = True
            if self.close_event is not None:
                self.close_event.set()


class _OldSignatureStreamClient:
    """A client predating `sources_out`: it rejects the extra keyword."""

    def __init__(self, chunks: list[str]):
        self.chunks = chunks
        self.closed = False

    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        try:
            for chunk in self.chunks:
                yield chunk
        finally:
            self.closed = True


def test_closing_the_wrapper_closes_the_inner_stream():
    client = _RecordingStreamClient(["one ", "two"])

    async def run():
        stream = _compat_chat_stream(client, "prompt", [], None, None)
        collected = []
        async with closing_stream(stream) as owned:
            async for chunk in owned:
                collected.append(chunk)
        return "".join(collected)

    assert asyncio.run(run()) == "one two"
    assert client.closed, "the wrapper closed itself but left chat_stream open"


def test_closing_mid_stream_closes_the_inner_stream_immediately():
    """A client disconnect: ``aclose()`` has to release the turn by the time it
    returns, not on a later loop turn."""
    client = _RecordingStreamClient(["first", "second", "third"])

    async def run():
        stream = _compat_chat_stream(client, "prompt", [], None, None)
        assert await anext(stream) == "first"
        await stream.aclose()
        return client.closed

    assert asyncio.run(run()) is True


def test_extra_kwargs_are_dropped_for_a_client_that_cannot_take_them():
    """The compatibility half of the wrapper still has to work: a client whose
    ``chat_stream`` has no ``sources_out`` must not be called with one."""
    client = _OldSignatureStreamClient(["answer"])

    async def run():
        stream = _compat_chat_stream(
            client, "prompt", [], None, None, sources_out=[],
        )
        return [chunk async for chunk in stream]

    assert asyncio.run(run()) == ["answer"]
    assert client.closed


def test_sources_are_passed_through_to_a_client_that_accepts_them():
    received: list[object] = []

    class _Sink:
        async def chat_stream(self, prompt, additional_context, session=None, images=None, *, sources_out=None):
            received.append(sources_out)
            yield "answer"

    sources: list[dict] = []
    client = _Sink()

    async def run():
        return [chunk async for chunk in _compat_chat_stream(
            client, "prompt", [], None, None, sources_out=sources,
        )]

    assert asyncio.run(run()) == ["answer"]
    assert received == [sources]
