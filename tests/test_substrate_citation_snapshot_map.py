"""Review #2: the two views of one turn must agree on a source's number.

M365 sends a cumulative ``messages`` snapshot AND incremental ``writeAtCursor``
deltas for the same turn, and it does not always render a citation the same
way in both: one live capture had ``【4-6f710b】`` in the snapshot against
``<cite>turn1search4</cite>`` in the deltas.

Both renderings name ONE source, but they normalise to unrelated keys, so the
tracker numbered them separately -- the snapshot said ``[4]`` where the deltas
said ``[1]``. ``_split_snapshot_lead`` then saw no common prefix, the delta's
replay of the opening looked like new text, and the reader was told the first
sentence twice.

Two things fix it, and both are pinned here: the source's renderings are
registered as ONE key as the reference metadata arrives, and the snapshot-lead
reconciliation tolerates a differing footnote NUMBER (never differing prose).
"""



from __future__ import annotations

import asyncio
import json

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


# --- review #2: the two renderings of ONE source, in one turn ---------------

CROSS_RENDER_REFS = dict([
    _reference("4-6f710b", "turn1search4", "4", "https://fastapi.tiangolo.com", "FastAPI"),
])
ANSWER_OPENING = "FastAPI 很快。"
ANSWER_REST = " 后面还有正文。"


def test_snapshot_and_deltas_rendering_one_source_differently_deliver_it_once(monkeypatch):
    """The review-#2 scenario: snapshot says 【4-6f710b】, deltas say <cite>turn1search4</cite>.

    Numbering the two renderings separately made the snapshot deliver ``[4]``
    where the delta delivered ``[1]``. `_split_snapshot_lead` then saw no
    prefix, so the delta's replay of the opening was forwarded and the reader
    was told the first sentence twice.
    """
    frames = [
        _snapshot(ANSWER_OPENING + "【4-6f710b】", CROSS_RENDER_REFS),
        _delta(ANSWER_OPENING + "<cite>turn1search4</cite>"),
        _delta(ANSWER_REST),
        _complete(ANSWER_OPENING + "【4-6f710b】" + ANSWER_REST, CROSS_RENDER_REFS),
    ]
    text, _sources = _collect(frames, monkeypatch)

    assert text == "FastAPI 很快。[4] 后面还有正文。"
    assert text.count(ANSWER_OPENING) == 1, f"opening delivered twice: {text!r}"


def test_deltas_then_snapshot_rendering_one_source_differently_deliver_it_once(monkeypatch):
    """Same turn, the deltas arriving first: order must not change the outcome."""
    frames = [
        _delta(ANSWER_OPENING + "<cite>turn1search4</cite>"),
        _snapshot(ANSWER_OPENING + "【4-6f710b】", CROSS_RENDER_REFS),
        _delta(ANSWER_REST),
        _complete(ANSWER_OPENING + "【4-6f710b】" + ANSWER_REST, CROSS_RENDER_REFS),
    ]
    text, _sources = _collect(frames, monkeypatch)

    assert text == "FastAPI 很快。[4] 后面还有正文。"
    assert text.count(ANSWER_OPENING) == 1, f"opening delivered twice: {text!r}"


def test_reference_map_reaches_the_cited_url(monkeypatch):
    """The number the body uses has to be the number the source is filed under,
    or the annotation lands on somebody else's marker."""
    frames = [
        _snapshot(ANSWER_OPENING + "【4-6f710b】", CROSS_RENDER_REFS),
        _delta(ANSWER_OPENING + "<cite>turn1search4</cite>"),
        _delta(ANSWER_REST),
        _complete(ANSWER_OPENING + "【4-6f710b】" + ANSWER_REST, CROSS_RENDER_REFS),
    ]
    text, sources = _collect(frames, monkeypatch)

    assert [(source["footnote"], source["url"]) for source in sources] == [
        (4, "https://fastapi.tiangolo.com")
    ]
    annotations = openai_url_citations_from_sources(text, sources)
    assert len(annotations) == 1
    assert annotations[0]["url"] == "https://fastapi.tiangolo.com"
    assert text[annotations[0]["start_index"]:annotations[0]["end_index"]] == "[4]"


def test_distinct_full_references_with_one_label_keep_their_own_urls(monkeypatch):
    refs = dict([
        _reference("1-aaaaaa", "turn1search0", "1", "https://a.example", "A"),
        _reference("1-bbbbbb", "turn1search1", "1", "https://b.example", "B"),
    ])
    snapshot = "A【1-aaaaaa】 B【1-bbbbbb】 end"
    delta = "A<cite>turn1search0</cite> B<cite>turn1search1</cite> end"
    text, sources = _collect([
        _snapshot(snapshot, refs), _delta(delta), _complete(snapshot, refs),
    ], monkeypatch)

    assert text == "A[1] B[2] end"
    annotations = openai_url_citations_from_sources(text, sources)
    assert [(a["url"], text[a["start_index"]:a["end_index"]]) for a in annotations] == [
        ("https://a.example", "[1]"), ("https://b.example", "[2]"),
    ]


def test_plain_snapshot_number_survives_a_suppressed_full_id_rendering(monkeypatch):
    refs = dict([
        _reference("1-aaaaaa", "turn1search0", "1", "https://a.example", "A"),
    ])
    text, sources = _collect([
        _snapshot("Claim [1]."),
        _delta("Claim <cite>turn1search0</cite>."),
        _complete("Claim [1].", refs),
    ], monkeypatch)

    assert text == "Claim [1]."
    assert [(s["footnote"], s["url"]) for s in sources] == [(1, "https://a.example")]
    annotation, = openai_url_citations_from_sources(text, sources)
    assert text[annotation["start_index"]:annotation["end_index"]] == "[1]"
