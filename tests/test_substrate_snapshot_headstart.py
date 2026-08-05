from __future__ import annotations

import asyncio
import json

from m365_copilot_openai_proxy.substrate_client import SIGNALR_SEP, SubstrateCopilotClient


# Frame-level reproduction of the SECOND form of "reply shows up twice", the one
# a live deployment still produced after the t==3 reconciliation was fixed.
#
# The mechanism is a head start, not a bad comparison. M365 sends TWO views of
# the answer over the same turn:
#
#   * writeAtCursor deltas -- strictly incremental, each carries only new text
#   * an `messages` snapshot -- CUMULATIVE, the whole answer so far, restated
#     in full every time it is sent
#
# _chat_stream_for_turn keeps the newest snapshot in `fallback_text` as its
# safety net for turns that stream nothing. But when the first delta arrives and
# a snapshot has already landed, it used to flush that whole snapshot first and
# only then start forwarding deltas:
#
#       if not yielded_any and fallback_text:
#           yield fallback_text
#
# The deltas, however, continue from where the model actually is -- they do not
# rewind to the start of the snapshot. So everything the model emitted between
# the snapshot boundary and the first forwarded delta is skipped: the answer
# arrives with HOLES punched mid-sentence. At t==3 the authoritative full text
# then fails to line up with that mutilated stream, coverage lands under the
# restatement threshold, and the tail gets appended -- the duplicate.
#
# Holes and duplicate are one bug seen from both ends, which is why a capture of
# it shows both at once: prose missing from the middle, a slab repeated at the
# end.

FULL_ANSWER = (
    "Python is a general-purpose language. "
    "It powers web backends, data science and automation. "
    "FastAPI builds on Starlette and Pydantic. "
    "It rivals Node.js in throughput."
)
# Where the upstream snapshot boundary falls; deltas resume from here.
SNAPSHOT_CUT = 82


def _fake_ws(messages: list[dict]):
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


def _client() -> SubstrateCopilotClient:
    client = SubstrateCopilotClient.__new__(SubstrateCopilotClient)
    client._token = "token"
    client._time_zone = "Asia/Shanghai"
    client._tone = "Magic"
    client._extra_tool_prompt = ""
    client._oid = "oid"
    client._tid = "tid"
    return client


def _delta(text: str) -> dict:
    return {"type": 1, "target": "update", "arguments": [{"writeAtCursor": text}]}


def _snapshot(text: str) -> dict:
    """An `update` frame carrying a cumulative messages snapshot, no delta."""
    return {
        "type": 1,
        "target": "update",
        "arguments": [{"messages": [{"author": "bot", "text": text}]}],
    }


def _complete(text: str) -> dict:
    return {"type": 2, "item": {"messages": [{"author": "bot", "text": text}]}}


def _collect(client: SubstrateCopilotClient, frames: list[dict], monkeypatch) -> str:
    import websockets

    monkeypatch.setattr(websockets, "connect", lambda *a, **k: _fake_ws(frames)())

    async def run() -> str:
        chunks = []
        async for chunk in client._chat_stream_for_turn(
            "q", "conv", "sess", is_start_of_session=True
        ):
            chunks.append(chunk)
        return "".join(chunks)

    return asyncio.run(run())


def test_snapshot_before_first_delta_does_not_punch_holes(monkeypatch):
    """The delivered answer must equal what the model said -- no gaps.

    A snapshot lands mid-turn, then deltas resume from the model's real position.
    The pre-fix code flushed the snapshot and appended those later deltas, which
    dropped the whole middle of the sentence.
    """
    head = FULL_ANSWER[:SNAPSHOT_CUT]
    frames = [
        _delta(head[:40]),
        _snapshot(head),
        _delta(FULL_ANSWER[SNAPSHOT_CUT:]),
        _complete(FULL_ANSWER),
    ]
    text = _collect(_client(), frames, monkeypatch)

    assert text == FULL_ANSWER, f"holes or duplication in delivered text: {text!r}"


def test_snapshot_arriving_before_any_delta_is_not_double_counted(monkeypatch):
    """Snapshot first, then deltas that continue past it.

    This is the exact live shape: nothing had been forwarded yet when the
    snapshot arrived, so the head-start branch fired and the answer both lost
    its middle and gained a repeated tail.
    """
    frames = [
        _snapshot(FULL_ANSWER[:SNAPSHOT_CUT]),
        _delta(FULL_ANSWER[SNAPSHOT_CUT:]),
        _complete(FULL_ANSWER),
    ]
    text = _collect(_client(), frames, monkeypatch)

    assert text == FULL_ANSWER
    # The clause straddling the snapshot boundary must survive intact.
    assert "data science and automation" in text
    assert text.count("FastAPI builds on Starlette") == 1


def test_turn_that_streams_only_a_snapshot_still_delivers_it(monkeypatch):
    """The safety net must keep working: no deltas at all => emit the snapshot.

    Some turns (short answers, cached results) never send writeAtCursor. The
    fallback exists for exactly those, and reconciliation at t==3 has to deliver
    the answer rather than nothing.
    """
    frames = [_snapshot(FULL_ANSWER), _complete(FULL_ANSWER)]
    text = _collect(_client(), frames, monkeypatch)

    assert text == FULL_ANSWER


def test_snapshot_then_deltas_that_restate_from_the_top(monkeypatch):
    """Deltas that DO rewind to the beginning must not produce a doubled answer.

    The opposite upstream behaviour from the test above: here the deltas replay
    the answer from its start after a snapshot was already seen. Whichever view
    a turn uses, the reader may only be told the answer once.
    """
    frames = [
        _snapshot(FULL_ANSWER[:SNAPSHOT_CUT]),
        _delta(FULL_ANSWER[:SNAPSHOT_CUT]),
        _delta(FULL_ANSWER[SNAPSHOT_CUT:]),
        _complete(FULL_ANSWER),
    ]
    text = _collect(_client(), frames, monkeypatch)

    assert text == FULL_ANSWER, f"answer restated: {text!r}"
