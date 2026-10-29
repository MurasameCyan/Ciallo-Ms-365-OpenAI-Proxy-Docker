"""Review #4: a source's citation span comes from the number the BODY used.

Dropping a URL-less source and then numbering the survivors by list position
puts a URL on somebody else's ``[n]``: with an internal (no URL) source on
``[1]`` and a public one on ``[2]``, the public URL was annotated over ``[1]``.

The numbers themselves are upstream's and may be sparse or out of order --
``【3-aa11bb】`` followed by ``【1-cc22dd】`` legitimately delivers ``A[3] B[4]``.
A footnote the body never emitted therefore collapses to a zero-width span at
end-of-text: no highlight, rather than a wrong one.
"""



from __future__ import annotations

import asyncio
import json

import pytest

from m365_copilot_openai_proxy.substrate_client import SIGNALR_SEP, SubstrateCopilotClient
from m365_copilot_openai_proxy.substrate_parse import (
    anthropic_web_citations_from_sources,
    openai_url_citations_from_sources,
)


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


# --- review #4: a URL-less internal source must not shift the public one ----

INTERNAL_AND_PUBLIC = "Internal [1], public [2]."
INTERNAL_AND_PUBLIC_REFS = dict([
    _reference("1-aaaaaa", "turn1file0", "1", "", "Internal doc"),
    _reference("2-bbbbbb", "turn1search1", "2", "https://public.example/a", "Public page"),
])


def test_url_less_internal_source_does_not_move_the_public_url(monkeypatch):
    """Both markers cite a source; only the second has a URL.

    Renumbering the surviving list by position put the public URL on ``[1]``.
    """
    frames = [
        _delta("Internal "),
        _delta("[1], public [2]."),
        _complete(INTERNAL_AND_PUBLIC, INTERNAL_AND_PUBLIC_REFS),
    ]
    text, sources = _collect(frames, monkeypatch)

    assert text == INTERNAL_AND_PUBLIC
    annotations = openai_url_citations_from_sources(text, sources)
    assert [a["url"] for a in annotations] == ["https://public.example/a"]
    assert text[annotations[0]["start_index"]:annotations[0]["end_index"]] == "[2]"

    citations = anthropic_web_citations_from_sources(text, sources)
    assert [c["encrypted_index"] for c in citations] == ["m365_2"]
    assert citations[0]["cited_text"] == "[2]"


def test_a_footnote_that_the_body_never_emitted_collapses_to_eof(monkeypatch):
    """Deliberate: no marker in the body -> a zero-width span at EOF.

    Upstream numbers the markers, so a source can carry a footnote the prose
    never shows. Emitting the annotation at EOF keeps its url/title instead of
    dropping the source, and never puts a highlight on somebody else's marker.
    """
    refs = dict([
        _reference("2-bbbbbb", "turn1search2", "2", "https://only.example", "Only"),
    ])
    frames = [
        _delta("正文没有脚注。"),
        _complete("正文没有脚注。", refs),
    ]
    text, sources = _collect(frames, monkeypatch)

    annotations = openai_url_citations_from_sources(text, sources)
    assert len(annotations) == 1
    assert annotations[0]["start_index"] == annotations[0]["end_index"] == len(text)


@pytest.mark.parametrize("marker,minimum", [
    ("\ue200cite\ue202turn1search9\ue201", 1),
    ("【9-cccccc】", 9),
])
def test_unmatched_body_identity_reserves_its_number(monkeypatch, marker, minimum):
    raw = f"Claim {marker}."
    refs = dict([
        _reference("1-aaaaaa", "turn1search0", "1", "https://other.example", "Other"),
    ])
    text, sources = _collect([_delta(raw), _complete(raw, refs)], monkeypatch)

    assert text == f"Claim [{minimum}]."
    assert len(sources) == 1
    assert sources[0]["footnote"] > minimum
    annotation, = openai_url_citations_from_sources(text, sources)
    assert annotation["start_index"] == annotation["end_index"] == len(text)
    citation, = anthropic_web_citations_from_sources(text, sources)
    assert citation["cited_text"] == "Other"


@pytest.mark.parametrize("syntax", ["[{n}]", "[^{n}^]"])
@pytest.mark.parametrize("public_only", [False, True])
def test_explicit_public_number_survives_reordered_or_sparse_sources(
    monkeypatch, syntax, public_only,
):
    public = _reference("2-bbbbbb", "turn1search1", "2", "https://public.example", "Public")
    internal = _reference("1-aaaaaa", "turn1file0", "1", "", "Internal")
    refs = dict([public] if public_only else [public, internal])
    raw = f"Internal {syntax.format(n=1)}, public {syntax.format(n=2)}."
    text, sources = _collect([_delta(raw), _complete(raw, refs)], monkeypatch)

    assert text == "Internal [1], public [2]."
    assert [(s["footnote"], s["url"]) for s in sources] == [(2, "https://public.example")]
    annotation, = openai_url_citations_from_sources(text, sources)
    assert text[annotation["start_index"]:annotation["end_index"]] == "[2]"
    citation, = anthropic_web_citations_from_sources(text, sources)
    assert citation["encrypted_index"] == "m365_2"
    assert citation["cited_text"] == "[2]"


def test_mixed_unmatched_identity_and_explicit_number_keep_distinct_annotations(monkeypatch):
    raw = "Unknown \ue200cite\ue202turn1search9\ue201, public [2]."
    refs = dict([
        _reference("2-bbbbbb", "turn1search1", "2", "https://public.example", "Public"),
        _reference("3-cccccc", "turn1search2", "3", "https://other.example", "Other"),
    ])
    text, sources = _collect([_delta(raw), _complete(raw, refs)], monkeypatch)

    assert text == "Unknown [1], public [2]."
    annotations = openai_url_citations_from_sources(text, sources)
    assert [(a["url"], text[a["start_index"]:a["end_index"]]) for a in annotations] == [
        ("https://public.example", "[2]"), ("https://other.example", ""),
    ]


@pytest.mark.parametrize("raw", ["value = data[1]", "value = data[1000000000]"])
@pytest.mark.parametrize("with_source", [False, True])
def test_ordinary_numeric_brackets_without_identity_are_not_citations(monkeypatch, with_source, raw):
    final = _complete(raw)
    if with_source:
        final["item"]["sourceAttributions"] = [
            {"providerDisplayName": "Other", "seeMoreUrl": "https://other.example"},
        ]
    text, sources = _collect([_delta(raw), final], monkeypatch)

    assert text == raw
    annotations = openai_url_citations_from_sources(text, sources)
    assert len(annotations) == int(with_source)
    assert all(a["start_index"] == a["end_index"] == len(text) for a in annotations)


@pytest.mark.parametrize("syntax", ["[1]", "[^1^]", "【1】"])
def test_conflicting_numeric_labels_cannot_select_a_claim_url(monkeypatch, syntax):
    raw = f"Ambiguous {syntax}."
    refs = dict([
        _reference("1-aaaaaa", "turn1search0", "1", "https://a.example", "A"),
        _reference("1-bbbbbb", "turn1search1", "1", "https://b.example", "B"),
    ])
    text, sources = _collect([_snapshot(raw, refs), _complete(raw, refs)], monkeypatch)

    assert text == "Ambiguous [1]."
    annotations = openai_url_citations_from_sources(text, sources)
    assert [a["url"] for a in annotations] == ["https://a.example", "https://b.example"]
    assert all(s["footnote"] > 1 for s in sources)
    assert all(a["start_index"] == a["end_index"] == len(text) for a in annotations)
