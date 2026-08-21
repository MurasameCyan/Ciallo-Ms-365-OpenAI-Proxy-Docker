"""Regression guard: a mid-stream upstream failure on the OpenAI SSE path must
reach the client as a normal ``chat.completion.chunk`` carrying the message in
``choices[0].delta.content`` -- never a bare ``{"error": ...}`` frame.

A strict OpenAI client indexes ``choices[0].delta.content`` on every data frame;
an error-only frame (no ``choices``) is rendered as ``null: [object Object]``,
which is exactly the client-visible failure that hid the real refusal reason.
That malformed frame has been reintroduced before, so both streaming generators
are pinned here. These tests fail against the old bare-error frame (no
``choices`` key, no error text in any content delta) and pass against the fix.
"""

from __future__ import annotations

import asyncio
import json

from m365_copilot_openai_proxy.response_helpers import _openai_stream
from m365_copilot_openai_proxy.routes_api_chat import _openai_stream_with_tools
from m365_copilot_openai_proxy.substrate_client import (
    SubstrateCopilotError,
    SubstrateThrottled,
)


class _FailingStreamClient:
    """Yield some partial text, then fail mid-stream like an unserved tone."""

    def __init__(self, pre_text: str, exc: Exception):
        self._pre = pre_text
        self._exc = exc

    async def chat_stream(self, prompt, additional_context=None, session=None, images=None):
        if self._pre:
            yield self._pre
        raise self._exc


def _drain(agen) -> list[str]:
    async def run() -> list[str]:
        return [frame async for frame in agen]

    return asyncio.run(run())


def _payloads(frames: list[str]):
    text = "".join(frames)
    objs = []
    for line in text.splitlines():
        if line.startswith("data: "):
            body = line[len("data: "):]
            if body != "[DONE]":
                objs.append(json.loads(body))
    return text, objs


def _joined_content(objs) -> str:
    return "".join(
        o["choices"][0]["delta"].get("content", "")
        for o in objs
        if o.get("choices")
    )


def test_openai_stream_upstream_error_reaches_content_not_bare_error_frame():
    client = _FailingStreamClient("部分内容", SubstrateCopilotError("boom"))
    done: list[str] = []
    frames = _drain(
        _openai_stream("m365-model", client, "hi", [], None, on_text_done=done.append)
    )
    text, objs = _payloads(frames)

    assert text.endswith("data: [DONE]\n\n")
    assert objs, "expected at least one data frame"
    # No strict-client-breaking bare-error frame: every payload is a normal chunk.
    assert all("error" not in o for o in objs)
    assert all("choices" in o for o in objs)
    content = _joined_content(objs)
    assert "部分内容" in content  # buffered pre-failure text preserved
    assert "⚠️ 上游错误：boom" in content
    assert any(o["choices"][0].get("finish_reason") == "stop" for o in objs)
    # The call-log hook records the same readable text the client received.
    assert done and "⚠️ 上游错误：boom" in done[-1]


def test_openai_stream_with_tools_upstream_error_reaches_content_not_bare_error_frame():
    client = _FailingStreamClient("部分内容", SubstrateCopilotError("boom"))
    call_record: dict = {}
    frames = _drain(
        _openai_stream_with_tools(
            "m365-model", client, "hi", [], None,
            call_record=call_record, tool_names={"Read"},
        )
    )
    text, objs = _payloads(frames)

    assert text.endswith("data: [DONE]\n\n")
    assert objs, "expected at least one data frame"
    assert all("error" not in o for o in objs)
    assert all("choices" in o for o in objs)
    content = _joined_content(objs)
    assert "部分内容" in content
    assert "⚠️ 上游错误：boom" in content
    assert any(o["choices"][0].get("finish_reason") == "stop" for o in objs)
    # The web call-log captures the upstream error for diagnostics.
    assert call_record.get("error") == "boom"


def test_openai_stream_throttle_marks_rate_limit_error_without_bare_error_frame():
    call_record: dict = {}
    frames = _drain(
        _openai_stream(
            "m365-model",
            _FailingStreamClient("", SubstrateThrottled("upstream result: Throttled")),
            "hi",
            [],
            call_record=call_record,
        )
    )
    _text, objs = _payloads(frames)

    assert all("error" not in obj for obj in objs)
    markers = [obj.get("m365_error") for obj in objs if obj.get("m365_error")]
    assert markers == [{"type": "rate_limit_error", "message": "upstream result: Throttled"}]
    assert call_record["error"] == "upstream result: Throttled"


def test_openai_tool_stream_throttle_marks_rate_limit_error_without_router_fallback():
    call_record: dict = {}
    frames = _drain(
        _openai_stream_with_tools(
            "m365-model",
            _FailingStreamClient("", SubstrateThrottled("upstream result: Throttled")),
            "hi",
            [],
            None,
            call_record=call_record,
            tool_names={"Read"},
        )
    )
    _text, objs = _payloads(frames)

    markers = [obj.get("m365_error") for obj in objs if obj.get("m365_error")]
    assert markers == [{"type": "rate_limit_error", "message": "upstream result: Throttled"}]
    assert call_record["error"] == "upstream result: Throttled"
