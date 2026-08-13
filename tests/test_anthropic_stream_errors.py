from __future__ import annotations

import asyncio
import json

import pytest

from m365_copilot_openai_proxy.response_helpers import _anthropic_stream
from m365_copilot_openai_proxy.routes_api_messages import _anthropic_stream_with_tools
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotError


class _FailingStreamClient:
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        raise SubstrateCopilotError("upstream broke")
        yield ""  # unreachable; marks this as an async generator


class _PartialThenFailingStreamClient:
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        yield "partial"
        raise SubstrateCopilotError("upstream broke")


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
