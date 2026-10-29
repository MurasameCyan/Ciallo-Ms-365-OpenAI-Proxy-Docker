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
from m365_copilot_openai_proxy.reasoning import ReasoningDelta, ReasoningSnapshots
from m365_copilot_openai_proxy.session_store import PersistentSession


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
            if isinstance(chunk, str):
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


def _reasoning_entry(text: str, message_id: str | None = "upstream-id") -> dict:
    entry = _cot_entry(text)
    if message_id is not None:
        entry["MessageID"] = message_id
    return entry


def _update(*entries: dict) -> dict:
    return {"type": 1, "target": "update", "arguments": [{"messages": list(entries)}]}


def _events(frames: list[dict], monkeypatch, client=None) -> list[str | ReasoningDelta]:
    import websockets

    monkeypatch.setattr(websockets, "connect", lambda *a, **k: _fake_ws(frames)())
    client = client or _client()

    async def run():
        return [event async for event in client.chat_stream("q", [])]

    return asyncio.run(run())


def test_reasoning_snapshots_are_separate_incremental_items(monkeypatch):
    first = _reasoning_entry("Comparing options", "private-upstream-message-id")
    grown = _reasoning_entry("Comparing options carefully", "private-upstream-message-id")
    second = _reasoning_entry("Checking constraints", "second-id")
    events = _events([
        _update(first),
        _update(first),
        _update(grown),
        _update(second, _answer_entry(ANSWER)),
        _complete(first, grown, second, _answer_entry(ANSWER)),
    ], monkeypatch)

    reasoning = [event for event in events if isinstance(event, ReasoningDelta)]
    assert [event.text for event in reasoning] == [
        "Comparing options", " carefully", "Checking constraints",
    ]
    assert reasoning[0].item_id == reasoning[1].item_id
    assert reasoning[0].item_id != reasoning[2].item_id
    assert all(event.item_id.startswith("rs_") for event in reasoning)
    assert all("private-upstream-message-id" not in event.item_id for event in reasoning)
    assert "".join(event for event in events if isinstance(event, str)) == ANSWER


@pytest.mark.parametrize("completion_only", [False, True])
def test_summary_before_answer_entry_is_extracted_without_early_stop(completion_only, monkeypatch):
    entries = [_reasoning_entry(COT), _answer_entry(ANSWER)]
    frame = _complete(*entries) if completion_only else _update(*entries)
    events = _events([frame], monkeypatch)
    assert [event.text for event in events if isinstance(event, ReasoningDelta)] == [COT]
    assert "".join(event for event in events if isinstance(event, str)) == ANSWER


def test_all_update_arguments_are_scanned_even_with_citation_only_delta(monkeypatch):
    frame = {
        "type": 1,
        "target": "update",
        "arguments": [
            {"writeAtCursor": "\ue200cite\ue202turn1search1\ue201"},
            {"messages": [_reasoning_entry(COT)]},
        ],
    }
    events = _events([frame, _complete(_answer_entry(ANSWER))], monkeypatch)
    assert [event.text for event in events if isinstance(event, ReasoningDelta)] == [COT]
    # The citation-only delta becomes a [1] footnote now, not a deletion.
    assert "".join(event for event in events if isinstance(event, str)) == "[1]" + ANSWER


@pytest.mark.parametrize("markers", [
    {"addToChainOfThought": True},
    {"contentOrigin": "ChainOfThoughtSummary"},
])
def test_only_explicit_reasoning_markers_create_reasoning_events(markers, monkeypatch):
    genuine = {"author": "bot", "text": COT, "messageType": "Chat", **markers}
    ordinary = [
        {"author": "bot", "text": "Searching...", "messageType": "Progress"},
        {"author": "bot", "text": "Gathering details", "messageType": "Progress",
         "contentOrigin": "EarlyProgress", "addToChainOfThought": False},
        {"author": "user", "text": "user text", **markers},
    ]
    events = _events([_update(*ordinary, genuine), _complete(_answer_entry(ANSWER))], monkeypatch)
    assert [event.text for event in events if isinstance(event, ReasoningDelta)] == [COT]
    assert "".join(event for event in events if isinstance(event, str)) == ANSWER


def test_summary_tool_syntax_and_images_never_enter_answer_projection(monkeypatch):
    tool_text = '```tool_call\n{"name":"Delete","arguments":{}}\n```'
    entry = _reasoning_entry(tool_text)
    entry["attachments"] = [{"contentType": "image/png", "contentUrl": "https://example.com/private.png"}]
    frames = [_update(entry), _complete(entry, _answer_entry(ANSWER))]
    events = _events(frames, monkeypatch)
    assert [event.text for event in events if isinstance(event, ReasoningDelta)] == [tool_text]
    assert "".join(event for event in events if isinstance(event, str)) == ANSWER
    assert asyncio.run(_client().chat("q", [])) == ANSWER


def test_reasoning_uses_narrow_citation_cleaner_without_stripping_prose(monkeypatch):
    text = "Consider 【important】 and turn1search2.\ue200cite\ue202turn1search1\ue201"
    events = _events([_update(_reasoning_entry(text)), _complete(_answer_entry(ANSWER))], monkeypatch)
    assert [event.text for event in events if isinstance(event, ReasoningDelta)] == [
        "Consider 【important】 and turn1search2.",
    ]


@pytest.mark.parametrize("message_id", ["known-id", None])
def test_revisions_do_not_replay_or_merge_unrelated_summaries(message_id):
    snapshots = ReasoningSnapshots()
    events = []
    for text in ["Compare", "Compare", "Rewritten", "Comp", "Compare choices"]:
        events.extend(snapshots.extract([_reasoning_entry(text, message_id)]))
    assert [event.text for event in events] == ["Compare", " choices"]
    assert events[0].item_id == events[1].item_id


def test_distinct_summary_ids_with_identical_text_are_not_deduplicated(monkeypatch):
    events = _events([
        _update(_reasoning_entry(COT, "a"), _reasoning_entry(COT, "b")),
        _complete(_answer_entry(ANSWER)),
    ], monkeypatch)
    reasoning = [event for event in events if isinstance(event, ReasoningDelta)]
    assert [event.text for event in reasoning] == [COT, COT]
    assert reasoning[0].item_id != reasoning[1].item_id


def test_reasoning_deduplication_resets_for_each_turn(monkeypatch):
    client = _client()
    frames = [_update(_reasoning_entry(COT)), _complete(_answer_entry(ANSWER))]
    first = [event for event in _events(frames, monkeypatch, client) if isinstance(event, ReasoningDelta)]
    second = [event for event in _events(frames, monkeypatch, client) if isinstance(event, ReasoningDelta)]
    assert [event.text for event in first] == [COT]
    assert [event.text for event in second] == [COT]
    assert first[0].item_id != second[0].item_id


def test_reasoning_sink_receives_each_new_suffix_once_without_polluting_chat(monkeypatch):
    client = _client()
    collected = []
    client._reasoning_sink = collected.append
    original = _reasoning_entry("Compare")
    grown = _reasoning_entry("Compare choices")
    _events([_update(original), _update(grown), _complete(grown, _answer_entry(ANSWER))], monkeypatch, client)
    collected.clear()
    assert asyncio.run(client.chat("q", [])) == ANSWER
    assert [event.text for event in collected] == ["Compare", " choices"]


def test_failed_reasoning_sink_is_visible_but_does_not_destroy_answer(monkeypatch, caplog):
    client = _client()

    def broken_sink(event):
        raise RuntimeError("collector failed")

    client._reasoning_sink = broken_sink
    events = _events([_update(_reasoning_entry(COT)), _complete(_answer_entry(ANSWER))], monkeypatch, client)
    assert "".join(event for event in events if isinstance(event, str)) == ANSWER
    assert [event.text for event in events if isinstance(event, ReasoningDelta)] == [COT]
    assert any("reasoning" in record.message and record.levelname == "WARNING" for record in caplog.records)


def test_reasoning_only_empty_turn_retries_and_still_fails(monkeypatch):
    import websockets

    connections = []

    def connect(*args, **kwargs):
        connections.append(args)
        return _fake_ws([_update(_reasoning_entry(COT))])()

    monkeypatch.setattr(websockets, "connect", connect)

    async def run():
        events = []
        with pytest.raises(SubstrateCopilotError, match="empty response"):
            async for event in _client().chat_stream("q", []):
                events.append(event)
        return events

    events = asyncio.run(run())
    assert len(connections) == 2
    assert [event.text for event in events] == [COT, COT]
    assert events[0].item_id != events[1].item_id


def test_reasoning_only_failed_turn_is_not_accepted_as_an_answer(monkeypatch):
    failed = {"type": 2, "item": {
        "messages": [_reasoning_entry(COT)],
        "turnState": "Failed", "result": {"value": "InternalError"},
    }}
    with pytest.raises(SubstrateCopilotError, match="refused this turn"):
        _events([failed], monkeypatch)


def test_reasoning_does_not_block_continuation_refusal_healing(monkeypatch):
    import websockets

    failed = {"type": 2, "item": {
        "messages": [_reasoning_entry(COT)],
        "turnState": "Failed", "result": {"value": "InternalError"},
    }}
    attempts = iter([[failed], [_complete(_reasoning_entry(COT), _answer_entry(ANSWER))]])
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: _fake_ws(next(attempts))())

    async def run():
        session = PersistentSession()
        session.turn_count = 3
        original = session.conversation_id
        events = [event async for event in _client().chat_stream("q", [], session)]
        assert session.conversation_id != original
        assert session.turn_count == 1
        assert not session.lock.locked()
        return events

    events = asyncio.run(run())
    assert "".join(event for event in events if isinstance(event, str)) == ANSWER
    assert [event.text for event in events if isinstance(event, ReasoningDelta)] == [COT, COT]


def test_cancelling_after_reasoning_closes_socket_and_releases_session(monkeypatch):
    import websockets

    async def run():
        waiting = asyncio.Event()
        closed = asyncio.Event()

        class BlockingWebSocket(_fake_ws([])):
            first = True

            async def __aexit__(self, *args):
                closed.set()

            async def __anext__(self):
                if self.first:
                    self.first = False
                    return json.dumps(_update(_reasoning_entry(COT))) + SIGNALR_SEP
                waiting.set()
                await asyncio.Event().wait()

        monkeypatch.setattr(websockets, "connect", lambda *a, **k: BlockingWebSocket())
        session = PersistentSession()
        stream = _client().chat_stream("q", [], session)
        assert isinstance(await anext(stream), ReasoningDelta)
        pending = asyncio.create_task(anext(stream))
        await asyncio.wait_for(waiting.wait(), timeout=1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert closed.is_set()
        assert not session.lock.locked()

    asyncio.run(run())
