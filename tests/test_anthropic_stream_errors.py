from __future__ import annotations

import asyncio
import json

import pytest

from m365_copilot_openai_proxy.response_helpers import _anthropic_stream
from m365_copilot_openai_proxy.routes_api_messages import _anthropic_stream_with_tools
from m365_copilot_openai_proxy.sse_stream import ANTHROPIC_PING, keepalive_stream
from m365_copilot_openai_proxy.substrate_client import (
    SubstrateCopilotError,
    SubstrateThrottled,
)


class _FailingStreamClient:
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        raise SubstrateCopilotError("upstream broke")
        yield ""  # unreachable; marks this as an async generator


class _PartialThenFailingStreamClient:
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        yield "partial"
        raise SubstrateCopilotError("upstream broke")


class _DelayedStreamClient:
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        await asyncio.sleep(0.03)
        yield "delayed answer"


class _ThrottledStreamClient:
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        raise SubstrateThrottled("upstream result: Throttled")
        yield ""  # unreachable; marks this as an async generator


def _parse_event(chunk: str) -> tuple[str, dict]:
    event = None
    data = None
    for line in chunk.splitlines():
        if line.startswith("event: "):
            event = line.removeprefix("event: ")
        elif line.startswith("data: "):
            data = json.loads(line.removeprefix("data: "))
    assert event is not None and data is not None
    return event, data


def _events(gen) -> list[tuple[str, dict]]:
    async def run():
        return [chunk async for chunk in gen]

    return [_parse_event(chunk) for chunk in asyncio.run(run())]


def _events_until_message_stop(gen) -> list[tuple[str, dict]]:
    async def run():
        events = []
        try:
            async for chunk in gen:
                parsed = _parse_event(chunk)
                events.append(parsed)
                if parsed[0] == "message_stop":
                    break
        finally:
            await gen.aclose()
        return events

    return asyncio.run(run())


@pytest.mark.parametrize(
    "stream",
    [
        lambda client, on_text_done: _anthropic_stream(
            "m365-copilot", client, "hi", [], on_text_done=on_text_done
        ),
        lambda client, on_text_done: _anthropic_stream_with_tools(
            "m365-copilot",
            client,
            "hi",
            [],
            tool_names={"Write"},
            on_text_done=on_text_done,
        ),
    ],
    ids=["without-tools", "with-tools"],
)
def test_anthropic_stream_errors_are_visible_and_end_cleanly(stream):
    recorded_text: list[str] = []
    events = _events(stream(_FailingStreamClient(), recorded_text.append))

    visible_text = "".join(
        data["delta"]["text"]
        for _event, data in events
        if data.get("type") == "content_block_delta"
        and data["delta"].get("type") == "text_delta"
    )
    assert visible_text == "⚠️ 上游错误：upstream broke"
    assert recorded_text == [visible_text]

    event_names = [event for event, _data in events]
    assert event_names[0] == "message_start"
    assert event_names.index("content_block_start") < event_names.index("content_block_delta")
    assert "error" not in event_names
    assert event_names[-3:] == ["content_block_stop", "message_delta", "message_stop"]
    assert events[-2][1]["delta"]["stop_reason"] == "end_turn"


@pytest.mark.parametrize(
    "stream",
    [
        lambda client, on_text_done: _anthropic_stream(
            "m365-copilot", client, "hi", [], on_text_done=on_text_done
        ),
        lambda client, on_text_done: _anthropic_stream_with_tools(
            "m365-copilot",
            client,
            "hi",
            [],
            tool_names={"Write"},
            on_text_done=on_text_done,
        ),
    ],
    ids=["without-tools", "with-tools"],
)
def test_anthropic_stream_records_error_before_terminal_event(stream):
    recorded_text: list[str] = []

    _events_until_message_stop(stream(_FailingStreamClient(), recorded_text.append))

    assert recorded_text == ["⚠️ 上游错误：upstream broke"]


@pytest.mark.parametrize(
    "text_transform,expected_prefix",
    [
        (None, "partial"),
        (lambda text: f"<{text}>", "<partial>"),
    ],
    ids=["direct", "transformed"],
)
def test_anthropic_partial_text_is_not_lost_or_duplicated_on_error(
    text_transform, expected_prefix,
):
    recorded_text: list[str] = []
    events = _events(_anthropic_stream(
        "m365-copilot",
        _PartialThenFailingStreamClient(),
        "hi",
        [],
        on_text_done=recorded_text.append,
        text_transform=text_transform,
    ))

    visible_text = "".join(
        data["delta"]["text"]
        for _event, data in events
        if data.get("type") == "content_block_delta"
        and data["delta"].get("type") == "text_delta"
    )
    assert visible_text == expected_prefix + "⚠️ 上游错误：upstream broke"
    assert recorded_text == [visible_text]


def test_anthropic_tool_stream_sends_keepalive_while_upstream_is_silent():
    events = _events(keepalive_stream(
        _anthropic_stream_with_tools(
            "m365-copilot",
            _DelayedStreamClient(),
            "hi",
            [],
            tool_names={"Write"},
        ),
        interval=0.005,
        heartbeat=ANTHROPIC_PING,
    ))

    event_names = [event for event, _data in events]
    assert event_names[:3] == ["message_start", "content_block_start", "ping"]
    assert event_names.count("ping") >= 2
    assert event_names[-3:] == ["content_block_stop", "message_delta", "message_stop"]


def test_anthropic_stream_throttle_emits_standard_rate_limit_error_event():
    call_record: dict = {}
    events = _events(_anthropic_stream(
        "m365-copilot",
        _ThrottledStreamClient(),
        "hi",
        [],
        call_record=call_record,
    ))

    errors = [data for event, data in events if event == "error"]
    assert errors == [{
        "type": "error",
        "error": {
            "type": "rate_limit_error",
            "message": "upstream result: Throttled",
        },
    }]
    assert call_record["error"] == "upstream result: Throttled"


def test_anthropic_tool_stream_throttle_emits_standard_rate_limit_error_event():
    call_record: dict = {}
    events = _events(_anthropic_stream_with_tools(
        "m365-copilot",
        _ThrottledStreamClient(),
        "hi",
        [],
        tool_names={"Read"},
        call_record=call_record,
    ))

    errors = [data for event, data in events if event == "error"]
    assert errors == [{
        "type": "error",
        "error": {
            "type": "rate_limit_error",
            "message": "upstream result: Throttled",
        },
    }]
    assert call_record["error"] == "upstream result: Throttled"


@pytest.mark.parametrize(
    "stream",
    [
        lambda client, on_response_done: _anthropic_stream(
            "m365-copilot",
            client,
            "hi",
            [],
            on_response_done=on_response_done,
        ),
        lambda client, on_response_done: _anthropic_stream_with_tools(
            "m365-copilot",
            client,
            "hi",
            [],
            tool_names={"Write"},
            on_response_done=on_response_done,
        ),
    ],
    ids=["without-tools", "with-tools"],
)
def test_anthropic_stream_failure_does_not_record_a_successful_response(
    stream,
):
    completed: list[dict] = []

    _events(stream(_FailingStreamClient(), completed.append))

    assert completed == []


@pytest.mark.parametrize(
    "stream",
    [
        lambda client, on_response_done: _anthropic_stream(
            "m365-copilot",
            client,
            "hi",
            [],
            on_response_done=on_response_done,
        ),
        lambda client, on_response_done: _anthropic_stream_with_tools(
            "m365-copilot",
            client,
            "hi",
            [],
            tool_names={"Write"},
            on_response_done=on_response_done,
        ),
    ],
    ids=["without-tools", "with-tools"],
)
def test_anthropic_stream_disconnect_before_response_completion_is_not_recorded(
    stream,
):
    completed: list[dict] = []

    async def disconnect_after_preamble():
        wrapped = keepalive_stream(
            stream(_DelayedStreamClient(), completed.append),
            interval=1,
            heartbeat=ANTHROPIC_PING,
        )
        try:
            for _ in range(3):
                await anext(wrapped)
        finally:
            await wrapped.aclose()

    asyncio.run(disconnect_after_preamble())

    assert completed == []
