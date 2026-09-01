"""ChatHub narration frames must never become the answer.

Live ChatHub interleaves the answer with Progress frames that narrate the turn --
a `ChainOfThoughtSummary` reasoning transcript, `Searching...`, `EarlyProgress`
"Gathering details...". The reverse scan that fills `fallback_text` took the LAST
non-user entry whatever it was, so narration could win it.

Measured, 2026-09-01, against production (`.probe/fallback_shapes.py`, three
search-triggering turns): the answer always arrived with NO messageType and
`contentOrigin: "DeepLeo"`; every non-answer that won the scan was a Progress frame,
plus an empty `ReferencesListComplete`.

It shipped. `.probe/cot_leak.py` turn P2 (tone Reasoning) delivered the transcript
`**Considering SSE vs WebSocket for idle-gap workloads** ...` appended to an 8.4 KB
answer, because the completion frame's last entry was that transcript and the t==3
reconciliation treats `fallback_text` as the authoritative full answer.

The frame shapes below are copied from those captures, not invented.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from m365_copilot_openai_proxy.substrate_client import (
    SIGNALR_SEP,
    SubstrateCopilotClient,
    SubstrateCopilotError,
)

ANSWER = (
    "Cloudflare does not document a fixed free-tier WebSocket idle timeout. "
    "Send an application-level heartbeat every 30 seconds instead."
)
# Verbatim shape of the transcript that leaked in production.
COT = (
    "**Considering SSE vs WebSocket for idle-gap workloads**  \n"
    "Exploring the differences between WebSocket and SSE for a proxy that must "
    "survive long quiet periods."
)
REFUSAL = "Sorry, I wasn't able to respond to that. Is there something else I can help with?"


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
    client._tone = "Reasoning"
    client._extra_tool_prompt = ""
    client._oid = "oid"
    client._tid = "tid"
    return client


def _delta(text: str) -> dict:
    return {"type": 1, "target": "update", "arguments": [{"writeAtCursor": text}]}


def _cot_snapshot(text: str = COT) -> dict:
    """Progress + ChainOfThoughtSummary + addToChainOfThought, as captured."""
    return {
        "type": 1,
        "target": "update",
        "arguments": [{"messages": [{
            "author": "bot",
            "text": text,
            "messageType": "Progress",
            "contentOrigin": "ChainOfThoughtSummary",
            "addToChainOfThought": True,
        }]}],
    }


def _progress_snapshot(text: str, origin: str | None, cot: bool) -> dict:
    entry: dict = {"author": "bot", "text": text, "messageType": "Progress"}
    if origin is not None:
        entry["contentOrigin"] = origin
    if cot:
        entry["addToChainOfThought"] = True
    return {"type": 1, "target": "update", "arguments": [{"messages": [entry]}]}


def _answer_snapshot(text: str) -> dict:
    return {
        "type": 1,
        "target": "update",
        "arguments": [{"messages": [{
            "author": "bot", "text": text, "contentOrigin": "DeepLeo",
        }]}],
    }


def _complete(*entries: dict) -> dict:
    return {"type": 2, "item": {"messages": list(entries)}}


def _answer_entry(text: str) -> dict:
    return {"author": "bot", "text": text, "contentOrigin": "DeepLeo"}


def _cot_entry(text: str = COT) -> dict:
    return {
        "author": "bot", "text": text, "messageType": "Progress",
        "contentOrigin": "ChainOfThoughtSummary", "addToChainOfThought": True,
    }


def _collect(frames: list[dict], monkeypatch) -> str:
    import websockets

    monkeypatch.setattr(websockets, "connect", lambda *a, **k: _fake_ws(frames)())

    async def run() -> str:
        chunks = []
        async for chunk in _client()._chat_stream_for_turn(
            "q", "conv", "sess", is_start_of_session=True
        ):
            chunks.append(chunk)
        return "".join(chunks)

    return asyncio.run(run())


def test_partial_stream_completed_from_the_answer_not_the_transcript(monkeypatch):
    """The measured defect: the transcript becomes the turn's authoritative full text.

    The completion frame lists the whole turn, so a transcript sitting after the
    answer won the scan and `fallback_text` held narration. Replaying a captured
    production turn (`.probe/cot_replay.py`, 277 frames) showed exactly that: the
    t==3 reconciliation was handed a 996-char transcript in place of the 9326-char
    answer.

    That turn happened to deliver correctly anyway -- it had streamed the whole
    answer, so the reconciliation had nothing left to add. The damage shows on a turn
    that streamed only PART of it: with narration as the fallback there is no
    authoritative text to complete the answer from, and the tail is lost.
    """
    head, tail = ANSWER[:60], ANSWER[60:]
    out = _collect([
        _delta(head),
        _complete(_answer_entry(ANSWER), _cot_entry()),
    ], monkeypatch)
    assert out == ANSWER, "the missing tail must come from the answer entry"
    assert COT not in out


def test_transcript_before_first_delta_is_not_the_answer_opening(monkeypatch):
    """The other reachable path: a transcript snapshot arms the head-start flush.

    `if not yielded_any and fallback_text: yield fallback_text` fires on the first
    real delta, so a transcript that won the scan just before it became the opening
    of the answer.
    """
    out = _collect([
        _cot_snapshot(),
        _delta(ANSWER),
        _complete(_answer_entry(ANSWER)),
    ], monkeypatch)
    assert out == ANSWER
    assert COT not in out


@pytest.mark.parametrize(
    ("text", "origin", "cot"),
    [
        ("Searching...", None, True),
        ("Gathering details…", "EarlyProgress", False),
        ("Searching...", None, False),
    ],
)
def test_progress_narration_never_wins_the_scan(text, origin, cot, monkeypatch):
    """All three measured Progress shapes, including the two with cot=false.

    A filter keyed only on the ChainOfThought markers -- which is what the upstream
    references key on -- would let `EarlyProgress` and the flagless `Searching...`
    through, so those two are the point of this case.
    """
    out = _collect([
        _progress_snapshot(text, origin, cot),
        _delta(ANSWER),
        _complete(_answer_entry(ANSWER)),
    ], monkeypatch)
    assert out == ANSWER
    assert text not in out


def test_narration_does_not_wipe_an_earlier_good_snapshot(monkeypatch):
    """A turn that streams NOTHING must still fall back to the answer snapshot.

    Narration used to overwrite `fallback_text`, so the safety net for a
    delta-less turn held narration instead of the answer.
    """
    out = _collect([
        _answer_snapshot(ANSWER),
        _cot_snapshot(),
        _progress_snapshot("Searching...", None, True),
        _complete(_answer_entry(ANSWER), _cot_entry()),
    ], monkeypatch)
    assert out == ANSWER


def test_empty_references_frame_does_not_blank_the_fallback(monkeypatch):
    """`ReferencesListComplete` carries no text and won the scan 3/24 times live.

    Winning it set `fallback_text` to "", disarming the only safety net a turn that
    streams nothing has. It has to end the completion frame too, otherwise the
    answer entry that follows repairs the fallback and the case proves nothing --
    live captures show this frame arriving last, after the references are resolved.
    """
    references = {
        "author": "bot", "text": "", "messageType": "ReferencesListComplete",
    }
    out = _collect([
        _answer_snapshot(ANSWER),
        {"type": 1, "target": "update", "arguments": [{"messages": [references]}]},
        _complete(_answer_entry(ANSWER), references),
    ], monkeypatch)
    assert out == ANSWER


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        # Every shape that won the scan in .probe/fallback_shapes.py, with the count
        # it won by, so a future capture can be compared against this list.
        ({"contentOrigin": "DeepLeo"}, True),                                   # 24
        ({"messageType": "Progress", "contentOrigin": "ChainOfThoughtSummary",
          "addToChainOfThought": True}, False),                                # 6
        ({"messageType": "Progress", "addToChainOfThought": True}, False),      # 5
        ({"messageType": "Progress", "contentOrigin": "EarlyProgress"}, False),  # 3
        ({"messageType": "ReferencesListComplete"}, False),                     # 3
        ({"messageType": "Progress"}, False),                                   # 1
        # The refusal, which must keep winning it.
        ({"contentOrigin": "BotConnection"}, True),
        # A transcript moved to some other messageType is still a transcript.
        ({"messageType": "Chat", "addToChainOfThought": True}, False),
        ({"messageType": "Chat", "contentOrigin": "ChainOfThoughtSummary"}, False),
        # Ordinary chat text stays an answer.
        ({"messageType": "Chat"}, True),
        ({}, True),
    ],
)
def test_is_answer_entry_matches_measured_shapes(entry, expected):
    from m365_copilot_openai_proxy.substrate_parse import _is_answer_entry

    assert _is_answer_entry(entry) is expected


def test_refusal_still_raises_through_the_filter(monkeypatch):
    """The canned refusal must keep winning the scan.

    It arrives with `contentOrigin: "BotConnection"` and no messageType, so the
    deny-list leaves it alone -- but if it were ever filtered out, a refused turn
    would silently return empty instead of raising, which is the failure the tone
    checks exist to prevent.
    """
    frames = [
        _progress_snapshot("Searching...", None, True),
        {"type": 2, "item": {
            "messages": [{
                "author": "bot", "text": REFUSAL, "contentOrigin": "BotConnection",
            }],
            "turnState": "Failed",
            "result": {"value": "InternalError"},
        }},
    ]
    with pytest.raises(SubstrateCopilotError, match="refused this turn"):
        _collect(frames, monkeypatch)
