from __future__ import annotations

import asyncio
import json

import pytest

from m365_copilot_openai_proxy import substrate_client
from m365_copilot_openai_proxy.substrate_client import (
    SIGNALR_SEP,
    SubstrateCopilotClient,
    SubstrateCopilotError,
    SubstrateThrottled,
)

REFUSAL = "Sorry, I wasn't able to respond to that. Is there something else I can help with?"


def _fake_ws(messages: list[dict]):
    """A SignalR WebSocket that replays `messages` then ends the turn (t==3)."""

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, data):
            return None

        async def recv(self):
            return "{}" + SIGNALR_SEP

        def __aiter__(self):
            self._messages = iter(
                [json.dumps(m) + SIGNALR_SEP for m in [*messages, {"type": 3}]]
            )
            return self

        async def __anext__(self):
            try:
                return next(self._messages)
            except StopIteration:
                raise StopAsyncIteration

    return FakeWebSocket


def _client(tone: str) -> SubstrateCopilotClient:
    client = SubstrateCopilotClient.__new__(SubstrateCopilotClient)
    client._token = "token"
    client._time_zone = "Asia/Shanghai"
    client._tone = tone
    client._extra_tool_prompt = ""
    client._oid = "oid"
    client._tid = "tid"
    return client


def _collect(client: SubstrateCopilotClient) -> list[str]:
    async def run():
        return [
            chunk
            async for chunk in client._chat_stream_for_turn(
                text="say hi",
                conv_id="conv",
                session_id="session",
                is_start_of_session=True,
            )
        ]

    return asyncio.run(run())


def test_canned_refusal_as_whole_answer_raises_with_tone_name(monkeypatch):
    """An unavailable tone (e.g. a mode M365 has withdrawn) answers with only the
    canned refusal and no streamed deltas. That must surface as an upstream error
    naming the mode, not as the assistant's reply."""
    complete = {"type": 2, "item": {"messages": [{"author": "bot", "text": REFUSAL}]}}
    monkeypatch.setattr(
        substrate_client.websockets, "connect", lambda *a, **k: _fake_ws([complete])()
    )

    with pytest.raises(SubstrateCopilotError) as excinfo:
        _collect(_client("Claude_Fable"))

    assert "Claude_Fable" in str(excinfo.value)


def test_refusal_sentence_inside_a_streamed_answer_is_passed_through(monkeypatch):
    """Guard against false positives: once the turn streams real deltas, the same
    sentence is ordinary model output and must reach the client untouched."""
    update = {"type": 1, "target": "update", "arguments": [{"writeAtCursor": "Sure. "}]}
    complete = {
        "type": 2,
        "item": {"messages": [{"author": "bot", "text": f"Sure. {REFUSAL}"}]},
    }
    monkeypatch.setattr(
        substrate_client.websockets,
        "connect",
        lambda *a, **k: _fake_ws([update, complete])(),
    )

    assert _collect(_client("Magic")) == ["Sure. ", REFUSAL]


def test_streamed_refusal_only_answer_is_passed_through(monkeypatch):
    """The check keys off "no deltas at all", so a turn that genuinely streams
    this text stays a normal reply."""
    update = {"type": 1, "target": "update", "arguments": [{"writeAtCursor": REFUSAL}]}
    monkeypatch.setattr(
        substrate_client.websockets, "connect", lambda *a, **k: _fake_ws([update])()
    )

    assert _collect(_client("Magic")) == [REFUSAL]


def test_failed_turn_state_raises_even_if_the_line_is_reworded(monkeypatch):
    """The primary signal is structural (turnState/result.value), so a rejected
    tone is still caught after Microsoft rewords the canned sentence."""
    complete = {
        "type": 2,
        "item": {
            "turnState": "Failed",
            "result": {"value": "InternalError", "message": "Something went wrong."},
            "messages": [{"author": "bot", "text": "Something went wrong."}],
        },
    }
    monkeypatch.setattr(
        substrate_client.websockets, "connect", lambda *a, **k: _fake_ws([complete])()
    )

    with pytest.raises(SubstrateCopilotError) as excinfo:
        _collect(_client("Claude_Opus"))

    assert "Claude_Opus" in str(excinfo.value)
    assert "InternalError" in str(excinfo.value)


def test_throttled_turn_raises_typed_upstream_error(monkeypatch):
    complete = {
        "type": 2,
        "item": {
            "turnState": "Failed",
            "result": {"value": "Throttled"},
        },
    }
    monkeypatch.setattr(
        substrate_client.websockets,
        "connect",
        lambda *a, **k: _fake_ws([complete])(),
    )

    with pytest.raises(SubstrateThrottled) as excinfo:
        _collect(_client("Claude_Sonnet"))

    assert "Throttled" in str(excinfo.value)
    assert "Claude_Sonnet" in str(excinfo.value)


def test_failed_turn_after_real_deltas_is_passed_through(monkeypatch):
    """A turn that streamed real content and only then failed keeps the content:
    dropping a partial answer would be worse than reporting the failure."""
    update = {"type": 1, "target": "update", "arguments": [{"writeAtCursor": "Half an "}]}
    complete = {
        "type": 2,
        "item": {"turnState": "Failed", "result": {"value": "InternalError"},
                 "messages": [{"author": "bot", "text": "Half an answer"}]},
    }
    monkeypatch.setattr(
        substrate_client.websockets,
        "connect",
        lambda *a, **k: _fake_ws([update, complete])(),
    )

    assert _collect(_client("Magic")) == ["Half an ", "answer"]


def test_two_empty_turns_raise_instead_of_returning_nothing(monkeypatch):
    """An unknown tone makes substrate drop the invoke: the turn ends with no
    frames at all. After the one retry, that must surface as an error rather than
    an empty assistant message."""
    monkeypatch.setattr(
        substrate_client.websockets, "connect", lambda *a, **k: _fake_ws([])()
    )

    async def run():
        return [
            chunk
            async for chunk in _client("Gpt_9_9_Chat")._stream_turn_with_retry(
                text="say hi",
                conv_id="conv",
                session_id="session",
                is_start_of_session=True,
            )
        ]

    with pytest.raises(SubstrateCopilotError) as excinfo:
        asyncio.run(run())

    assert "Gpt_9_9_Chat" in str(excinfo.value)
