from __future__ import annotations

import asyncio

from m365_copilot_openai_proxy.sse_stream import keepalive_stream


def test_keepalive_stream_emits_comments_while_source_is_silent():
    async def source():
        await asyncio.sleep(0.02)
        yield "payload"

    async def run():
        return [item async for item in keepalive_stream(source(), interval=0.001)]

    items = asyncio.run(run())

    assert ": keepalive\n\n" in items
    assert items[-1] == "payload"


def test_keepalive_stream_closes_source_when_consumer_stops():
    cancelled = False
    closed = False

    async def source():
        nonlocal cancelled, closed
        try:
            await asyncio.Event().wait()
            yield "never"
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            closed = True

    async def run():
        stream = keepalive_stream(source(), interval=0.001)
        await anext(stream)
        await stream.aclose()

    asyncio.run(run())

    assert cancelled
    assert closed
