"""A tail the tracker is still holding must not be sent twice.

The tracker holds a tail that may yet complete a marker. At the completion
frame the answer is reconciled against upstream's own full text -- and a hold
that has not been released yet counts as text the reader does not have, so the
reconciliation appends it. The reader then sees it twice:

    deltas: A[3]B    hold: [4]    reconciled answer: A[3]B[4]
    delivered: A[3]B[4][4]

The hold has to be released before the comparison, and the run it releases is
what the deltas had already reached.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from m365_copilot_openai_proxy.substrate_client import SIGNALR_SEP, SubstrateCopilotClient
from m365_copilot_openai_proxy.substrate_parse import openai_url_citations_from_sources


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


def _snapshot(text: str, references: dict | None = None) -> dict:
    args: dict = {"messages": [{"author": "bot", "text": text, "contentOrigin": "DeepLeo"}]}
    if references is not None:
        args["references"] = references
    return {"type": 1, "target": "update", "arguments": [args]}


def _complete(text: str, references: dict | None = None) -> dict:
    item: dict = {"messages": [{"author": "bot", "text": text, "contentOrigin": "DeepLeo"}]}
    if references is not None:
        item["references"] = references
    return {"type": 2, "item": item}


def _reference(key: str, reference_id: str, label: str, url: str, title: str) -> tuple[str, dict]:
    """The modern ``references`` map shape, verbatim from a live capture."""
    return key, {
        "targetLink": url,
        "displayData": {
            "type": "text/json",
            "renderType": "CITATION",
            "content": json.dumps({
                "metadata": {"referenceId": reference_id, "type": "Web"},
                "label": label,
                "providerDisplayName": title,
            }),
        },
        "isCitedInResponse": True,
    }


def _collect(frames: list[dict], monkeypatch) -> tuple[str, list[dict]]:
    import websockets

    monkeypatch.setattr(websockets, "connect", lambda *a, **k: _fake_ws(frames)())

    async def run():
        chunks: list[str] = []
        sources: list[dict] = []
        async for chunk in _client()._chat_stream_for_turn(
            "q", "conv", "sess", is_start_of_session=True, sources_out=sources,
        ):
            if isinstance(chunk, str):
                chunks.append(chunk)
        return "".join(chunks), sources

    return asyncio.run(run())


def test_sparse_bracket_numbers_anchor_each_span_on_its_own_marker(monkeypatch):
    """【3-aa11bb】 then 【1-cc22dd】 -> A[3]B[4].

    The body skips 2 and the second source lands on 4, which the body does
    carry. What must not happen is a span drifting onto the neighbour's
    marker, which is what the position-based numbering did.
    """
    refs = dict([
        _reference("3-aa11bb", "turn1search3", "3", "https://a.example", "A"),
        _reference("1-cc22dd", "turn1search1", "1", "https://b.example", "B"),
    ])
    frames = [
        _delta("A【3-aa11bb】B【1-cc22dd】"),
        _complete("A【3-aa11bb】B【1-cc22dd】", refs),
    ]
    text, sources = _collect(frames, monkeypatch)

    assert text == "A[3]B[4]"
    spans = {
        a["url"]: text[a["start_index"]:a["end_index"]]
        for a in openai_url_citations_from_sources(text, sources)
    }
    assert spans == {"https://a.example": "[3]", "https://b.example": "[4]"}


@pytest.mark.parametrize("snapshot_first", [True, False])
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("value = data[0]", "value = data[0]"),
        ("Alpha \ue200cite\ue202turn1search0\ue201", "Alpha [1]"),
        ("Array prefix [1, 2", "Array prefix [1, 2"),
    ],
)
def test_snapshot_delivered_held_tail_is_not_replayed(raw, expected, snapshot_first, monkeypatch):
    frames = [_snapshot(raw), _delta(raw)] if snapshot_first else [_delta(raw), _snapshot(raw)]
    text, _sources = _collect([*frames, _complete(raw)], monkeypatch)

    assert text == expected


def test_held_tail_beyond_snapshot_still_reaches_the_reader(monkeypatch):
    text, _sources = _collect([
        _snapshot("values[0]"),
        _delta("values[0] + values[0]"),
        _complete("values[0] + values[0]"),
    ], monkeypatch)

    assert text == "values[0] + values[0]"


def test_late_reference_metadata_keeps_urls_on_their_own_claims(monkeypatch):
    early = _snapshot("")
    early["arguments"][0]["sourceAttributions"] = [
        {"providerDisplayName": "A", "seeMoreUrl": "https://a.example"},
        {"providerDisplayName": "B", "seeMoreUrl": "https://b.example"},
    ]
    raw = "B<cite>turn1search1</cite> A<cite>turn1search0</cite> end"
    refs = dict([
        _reference("1-aaaaaa", "turn1search0", "1", "https://a.example", "A"),
        _reference("2-bbbbbb", "turn1search1", "2", "https://b.example", "B"),
    ])
    text, sources = _collect([early, _delta(raw), _complete(raw, refs)], monkeypatch)

    assert text == "B[1] A[2] end"
    assert {
        annotation["url"]: text[annotation["start_index"]:annotation["end_index"]]
        for annotation in openai_url_citations_from_sources(text, sources)
    } == {"https://b.example": "[1]", "https://a.example": "[2]"}


def test_reference_keeps_its_number_when_a_later_frame_supplies_the_url(monkeypatch):
    early = dict([_reference("1-aaaaaa", "turn1search0", "1", "", "A")])
    enriched = dict([_reference("1-aaaaaa", "turn1search0", "1", "https://a.example", "A")])
    raw = "Claim <cite>turn1search0</cite>."
    text, sources = _collect([_snapshot("", early), _delta(raw), _complete(raw, enriched)], monkeypatch)

    assert text == "Claim [1]."
    assert [
        (annotation["url"], text[annotation["start_index"]:annotation["end_index"]])
        for annotation in openai_url_citations_from_sources(text, sources)
    ] == [("https://a.example", "[1]")]
