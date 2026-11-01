from __future__ import annotations

import asyncio

import json

from m365_copilot_openai_proxy.sse_stream import (
    SSE_KEEPALIVE_COMMENT,
    chat_keepalive_stream,
    keepalive_stream,
    responses_keepalive_stream,
)


def _collect(stream_factory, source, monkeypatch):
    async def run():
        return [item async for item in stream_factory(source(), interval=0.001)]

    return asyncio.run(run())


def _chunk(finish_reason=None, delta=None):
    body = {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "m",
            "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish_reason}]}
    return f"data: {json.dumps(body)}\n\n"


def test_chat_heartbeat_is_an_empty_delta_on_the_live_completion_only(monkeypatch):
    async def source():
        await asyncio.sleep(0.02)
        yield _chunk(delta={"role": "assistant"})
        await asyncio.sleep(0.02)
        yield _chunk(finish_reason="stop")
        await asyncio.sleep(0.02)
        yield "data: [DONE]\n\n"

    items = _collect(chat_keepalive_stream, source, monkeypatch)
    first = items.index(_chunk(delta={"role": "assistant"}))
    finish = items.index(_chunk(finish_reason="stop"))
    assert set(items[:first]) == {SSE_KEEPALIVE_COMMENT}
    beats = items[first + 1:finish]
    assert beats and all(json.loads(beat[6:])["choices"][0] == {"index": 0, "delta": {}, "finish_reason": None} for beat in beats)
    assert all(json.loads(beat[6:])["id"] == "chatcmpl-1" for beat in beats)
    assert set(items[finish + 1:-1]) == {SSE_KEEPALIVE_COMMENT}


def _event(kind, sequence):
    return f"event: {kind}\ndata: {json.dumps({'type': kind, 'sequence_number': sequence})}\n\n"


def test_responses_keepalive_events_keep_sequence_numbers_strictly_increasing(monkeypatch):
    async def source():
        await asyncio.sleep(0.02)
        yield _event("response.created", 0)
        await asyncio.sleep(0.02)
        yield _event("response.output_text.delta", 1)
        await asyncio.sleep(0.02)
        yield _event("response.completed", 2)
        await asyncio.sleep(0.02)

    items = _collect(responses_keepalive_stream, source, monkeypatch)
    events = [json.loads(item.split("data: ", 1)[1]) for item in items if "data: " in item]
    sequences = [event["sequence_number"] for event in events]
    assert sequences == list(range(len(sequences)))
    assert [event["type"] for event in events if event["type"] != "keepalive"] == [
        "response.created", "response.output_text.delta", "response.completed",
    ]
    assert any(event["type"] == "keepalive" for event in events)
    assert items[0] == SSE_KEEPALIVE_COMMENT and items[-1] == SSE_KEEPALIVE_COMMENT


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
