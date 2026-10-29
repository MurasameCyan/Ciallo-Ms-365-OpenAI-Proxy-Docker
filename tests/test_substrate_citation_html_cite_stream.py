"""A ``<cite>`` title must survive the real frame loop, not just the tracker.

The tracker-level cases live in ``test_substrate_citation_html_cite``. This
drives the same distinction through ``chat_stream``, where the snapshot and the
deltas can disagree about how the very same sentence is rendered: HTML's
``<cite>Moby Dick</cite>`` is a title that must arrive intact, while
``<cite>turn1search7</cite>`` beside it is a citation that must become ``[1]``.
"""

from __future__ import annotations

import asyncio
import json

from m365_copilot_openai_proxy.substrate_client import SIGNALR_SEP, SubstrateCopilotClient


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


# --- the <cite> element is not always a citation ---------------------------

def test_html_cite_title_is_delivered_intact_through_the_stream(monkeypatch):
    frames = [
        _delta("The novel "),
        _delta("<cite>Moby Dick</cite>"),
        _delta(" is referenced."),
        _complete("The novel <cite>Moby Dick</cite> is referenced."),
    ]
    text, _sources = _collect(frames, monkeypatch)

    assert text == "The novel <cite>Moby Dick</cite> is referenced."


def test_html_cite_title_and_a_citation_tag_in_the_same_turn(monkeypatch):
    frames = [
        _delta("The novel <cite>Moby Dick</cite> is good"),
        _delta("<cite>turn1search7</cite>"),
        _complete("The novel <cite>Moby Dick</cite> is good<cite>turn1search7</cite>"),
    ]
    text, _sources = _collect(frames, monkeypatch)

    assert text == "The novel <cite>Moby Dick</cite> is good[1]"
