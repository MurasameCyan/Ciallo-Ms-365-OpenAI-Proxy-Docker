"""Merely DECLARING a tool must not cost the answer its sources.

A request with a non-empty ``tools`` list takes the tool-capable stream
(`_responses_stream_with_tools` / `_anthropic_stream_with_tools`), whether or
not the model ends up calling anything. Those two paths used to collect no
sources at all, so adding an optional tool to an otherwise identical request
silently dropped every citation -- the answer still cited ``[1]``, and the
client had nowhere to point it.

Event ORDER matters as much as presence: a client builds its content blocks
from the stream, so an annotation has to arrive before the block it belongs to
is closed, and on the same index as the text it annotates.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time

import pytest
import websockets
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings

from m365_copilot_openai_proxy.response_helpers import _responses_stream_with_tools
from m365_copilot_openai_proxy.routes_api_messages import _anthropic_stream_with_tools
from m365_copilot_openai_proxy.substrate_client import SIGNALR_SEP, SubstrateCopilotClient

ANSWER = "有雷阵雨[1]"
SOURCES = [{
    "title": "Weather",
    "url": "https://news.weather.com.cn/a",
    "snippet": "雷阵雨",
    "ref_key": "1-aaaaaa",
    "ref_id": "turn1search1",
    "label": "1",
}]


class _CitingClient:
    """Streams an answer that cites ``[1]`` and declares the matching source.

    It never returns a tool call: the point is that the tool was only DECLARED.
    """

    def __init__(self, reply: str = ANSWER):
        self.reply = reply
        self.calls: list[object] = []

    async def chat_stream(self, prompt, additional_context, session=None, images=None, *, sources_out=None):
        self.calls.append(sources_out)
        assert sources_out is not None, "the tool path collected no sources at all"
        sources_out.clear()
        sources_out.extend(dict(source) for source in SOURCES)
        yield self.reply


def _events(gen) -> list[dict]:
    async def run():
        return [chunk async for chunk in gen]

    events = []
    for chunk in asyncio.run(run()):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


# --- OpenAI Responses ------------------------------------------------------

def test_responses_stream_with_declared_tool_annotates_the_text():
    events = _events(_responses_stream_with_tools(
        "m365-copilot",
        _CitingClient(),
        "今天天气",
        [],
        response_tools=[{"type": "function", "name": "get_weather",
                         "parameters": {"type": "object", "properties": {}}}],
        tool_names={"get_weather"},
    ))

    completed = [e for e in events if e["type"] == "response.completed"]
    assert completed, [e["type"] for e in events]
    output = completed[-1]["response"]["output"]
    message = next(item for item in output if item["type"] == "message")
    annotations = message["content"][0]["annotations"]

    assert [a["type"] for a in annotations] == ["url_citation"]
    assert annotations[0]["url"] == "https://news.weather.com.cn/a"
    assert ANSWER[annotations[0]["start_index"]:annotations[0]["end_index"]] == "[1]"


def test_responses_annotation_events_precede_output_text_done():
    """A client assembling the item from the stream needs the annotation before
    the text block it belongs to is declared finished."""
    events = _events(_responses_stream_with_tools(
        "m365-copilot",
        _CitingClient(),
        "今天天气",
        [],
        response_tools=[{"type": "function", "name": "get_weather",
                         "parameters": {"type": "object", "properties": {}}}],
        tool_names={"get_weather"},
    ))

    added = [e for e in events if e["type"] == "response.output_text.annotation.added"]
    done = [e for e in events if e["type"] == "response.output_text.done"]
    assert len(added) == 1 and len(done) == 1
    assert added[0]["annotation"]["url"] == "https://news.weather.com.cn/a"
    assert added[0]["sequence_number"] < done[0]["sequence_number"]

    # Same content block as the text it annotates.
    assert added[0]["output_index"] == done[0]["output_index"]
    assert added[0]["content_index"] == done[0]["content_index"] == 0
    assert added[0]["item_id"] == done[0]["item_id"]


def test_responses_declared_tool_that_is_not_called_still_annotates():
    """The declared tool produced no call, so the output holds only the message
    -- and that message must still carry the citation."""
    events = _events(_responses_stream_with_tools(
        "m365-copilot",
        _CitingClient("没有工具可用的普通回答[1]"),
        "今天天气",
        [],
        response_tools=[{"type": "function", "name": "get_weather",
                         "parameters": {"type": "object", "properties": {}}}],
        tool_names={"get_weather"},
    ))

    output = [e for e in events if e["type"] == "response.completed"][-1]["response"]["output"]
    assert [item["type"] for item in output] == ["message"]
    assert output[0]["content"][0]["annotations"][0]["url"] == "https://news.weather.com.cn/a"


def test_responses_tool_call_output_carries_no_annotations_of_its_own():
    """Annotations belong to the assistant message, not to the function_call
    items that sit beside it."""
    events = _events(_responses_stream_with_tools(
        "m365-copilot",
        _CitingClient('好的。\n\n```tool_call\n{"name":"get_weather",'
                      '"arguments":{"city":"Paris"}}\n```'),
        "今天天气",
        [],
        response_tools=[{"type": "function", "name": "get_weather",
                         "parameters": {"type": "object",
                                        "properties": {"city": {"type": "string"}},
                                        "required": ["city"]}}],
        tool_names={"get_weather"},
    ))

    output = [e for e in events if e["type"] == "response.completed"][-1]["response"]["output"]
    function_calls = [item for item in output if item["type"] == "function_call"]
    assert [call["name"] for call in function_calls] == ["get_weather"]
    assert "annotations" not in json.dumps(function_calls)


# --- Anthropic Messages ----------------------------------------------------

def test_messages_stream_with_declared_tool_emits_citations_delta():
    events = _events(_anthropic_stream_with_tools(
        "m365-copilot",
        _CitingClient(),
        "今天天气",
        [],
        tool_names={"get_weather"},
    ))

    citations = [
        event["delta"]["citation"]
        for event in events
        if event.get("type") == "content_block_delta"
        and event["delta"].get("type") == "citations_delta"
    ]
    assert [c["type"] for c in citations] == ["web_search_result_location"]
    assert citations[0]["url"] == "https://news.weather.com.cn/a"
    assert citations[0]["cited_text"] == "[1]"


def test_messages_citations_delta_precedes_content_block_stop():
    """The text block is still open when the citations arrive, and they have to
    name THAT block -- otherwise the SDK drops them onto nothing."""
    events = _events(_anthropic_stream_with_tools(
        "m365-copilot",
        _CitingClient(),
        "今天天气",
        [],
        tool_names={"get_weather"},
    ))

    types = [event["type"] for event in events]
    citation_index = next(
        index for index, event in enumerate(events)
        if event["type"] == "content_block_delta"
        and event["delta"].get("type") == "citations_delta"
    )
    stop_index = types.index("content_block_stop")
    assert citation_index < stop_index

    text_start = next(
        event for event in events
        if event["type"] == "content_block_start"
        and event["content_block"]["type"] == "text"
    )
    assert events[citation_index]["index"] == text_start["index"]


def test_messages_declared_tool_with_a_tool_use_block_keeps_text_citations():
    """A turn that DOES call a tool still cites: the text block and the tool_use
    block are separate content blocks of one message."""
    events = _events(_anthropic_stream_with_tools(
        "m365-copilot",
        _CitingClient('好的[1]。\n\n```tool_call\n{"name":"get_weather",'
                      '"arguments":{"city":"Paris"}}\n```'),
        "今天天气",
        [],
        tool_names={"get_weather"},
    ))

    starts = [e for e in events if e["type"] == "content_block_start"]
    assert [s["content_block"]["type"] for s in starts] == ["text", "tool_use"]

    text_index = starts[0]["index"]
    citations = [
        event for event in events
        if event["type"] == "content_block_delta"
        and event["delta"].get("type") == "citations_delta"
    ]
    assert [e["index"] for e in citations] == [text_index]
    assert citations[0]["delta"]["citation"]["url"] == "https://news.weather.com.cn/a"


_READ_CALL = '```tool_call\n{"name":"Read","arguments":{"file_path":"/tmp/a.txt"}}\n```'
_ROUTER_CALL = 'CALL_TOOL: Read({"file_path":"/tmp/a.txt"})'
_CITED = "Adopted evidence \ue200cite\ue202turn1search0\ue201."
_DRAFT = "Discarded draft \ue200cite\ue202turn1search0\ue201."
_ADOPTED_URL = "https://adopted.example/evidence"
_DISCARDED_URL = "https://discarded.example/evidence"
_CLASSIFIER_URL = "https://classifier.example/evidence"
_READ_SCHEMA = {
    "type": "object",
    "properties": {"file_path": {"type": "string"}},
    "required": ["file_path"],
}


class _PlannerSocket:
    def __init__(self, text, url):
        item = {"messages": [{"author": "bot", "text": text, "contentOrigin": "DeepLeo"}]}
        if url is not None:
            item["references"] = {"1-aaaaaa": {
                "targetLink": url,
                "displayData": {
                    "type": "text/json",
                    "renderType": "CITATION",
                    "content": json.dumps({
                        "metadata": {"referenceId": "turn1search0", "type": "Web"},
                        "label": "1",
                        "providerDisplayName": "Evidence",
                    }),
                },
                "isCitedInResponse": True,
            }}
        self.frames = iter([
            {"type": 1, "target": "update", "arguments": [{"writeAtCursor": text}]},
            {"type": 2, "item": item},
            {"type": 3},
        ])
        self.closed = False
        self.invocations = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed = True

    async def send(self, text):
        frame = json.loads(text.rstrip(SIGNALR_SEP))
        self.invocations.extend(frame.get("arguments", []))

    async def recv(self):
        return "{}" + SIGNALR_SEP

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return json.dumps(next(self.frames)) + SIGNALR_SEP
        except StopIteration:
            raise StopAsyncIteration


def _planner_app(tmp_path, monkeypatch, mode, turns):
    pending = list(turns)
    sockets = []

    def connect(url, **_kwargs):
        assert pending, "the planner spent an unexpected extra upstream turn"
        stage, text, source_url = pending.pop(0)
        assert ("gptId=" in url) == (stage == "studio")
        socket = _PlannerSocket(text, source_url)
        sockets.append(socket)
        return socket

    monkeypatch.setattr(websockets, "connect", connect)
    payload = base64.urlsafe_b64encode(json.dumps({
        "aud": "https://substrate.office.com/", "tid": "tenant-a", "oid": "object-a",
        "exp": int(time.time()) + 3600,
    }).encode()).decode().rstrip("=")
    token = f"eyJhbGciOiJub25lIn0.{payload}."

    def factory(**kwargs):
        return SubstrateCopilotClient(
            kwargs["token"], tone=kwargs.get("tone", "Magic"),
            studio_agent_id=kwargs.get("studio_agent_id", ""),
        )

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""),
        copilot_client_factory=factory,
    )
    account = app.state.account_store.add(name="Studio", token=token)
    app.state.account_store.set_studio_agent_id(account.id, "title.bot.gpt.default")
    key = app.state.key_store.add(name="Planner citations", account_id=account.id)
    app.state.key_store.update(key.id, tool_planning_mode=mode)
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {key.key}"
    return client, pending, sockets


def _planner_request(endpoint, streaming):
    body = {"model": "m365-copilot", "stream": streaming}
    if endpoint == "responses":
        body.update(input="Read /tmp/a.txt", tools=[{
            "type": "function", "name": "Read", "parameters": _READ_SCHEMA,
        }])
    else:
        body.update(
            messages=[{"role": "user", "content": "Read /tmp/a.txt"}], max_tokens=256,
            tools=[{"name": "Read", "description": "Read a file", "input_schema": _READ_SCHEMA}],
        )
    return body


def _planner_output(response, endpoint, streaming):
    assert response.status_code == 200, response.text
    if streaming:
        events = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith("data: ")]
        assert not any(event["type"] in {"error", "response.failed"} for event in events)
        if endpoint == "responses":
            body = next(event["response"] for event in events if event["type"] == "response.completed")
        else:
            text = "".join(event["delta"]["text"] for event in events
                           if event.get("delta", {}).get("type") == "text_delta")
            tools = [event["content_block"] for event in events
                     if event["type"] == "content_block_start"
                     and event["content_block"]["type"] == "tool_use"]
            citations = [event["delta"]["citation"] for event in events
                         if event.get("delta", {}).get("type") == "citations_delta"]
            assert events[-1]["type"] == "message_stop"
            return text, tools, citations
    else:
        body = response.json()
    if endpoint == "responses":
        parts = [part for item in body["output"] if item["type"] == "message"
                 for part in item["content"] if part["type"] == "output_text"]
        return (
            "".join(part["text"] for part in parts),
            [item for item in body["output"] if item["type"] == "function_call"],
            [citation for part in parts for citation in part.get("annotations", [])],
        )
    return (
        "".join(block["text"] for block in body["content"] if block["type"] == "text"),
        [block for block in body["content"] if block["type"] == "tool_use"],
        [citation for block in body["content"] for citation in block.get("citations", [])],
    )


@pytest.mark.parametrize("endpoint", ["messages", "responses"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(("mode", "turns", "tool_names", "source_urls"), [
    pytest.param("studio", [
        ("studio", _DRAFT, _DISCARDED_URL), ("ordinary", _ROUTER_CALL, None),
    ], ["Read"], [], id="discard-studio-adopt-pure-router-call"),
    pytest.param("studio", [
        ("studio", _CITED + "\n\n" + _READ_CALL, _ADOPTED_URL),
    ], ["Read"], [_ADOPTED_URL], id="keep-studio-tool-answer-sources"),
    pytest.param("studio", [
        ("studio", _CITED + "\n\nNO_TOOL_NEEDED", _ADOPTED_URL),
    ], [], [_ADOPTED_URL], id="keep-studio-explicit-no-tool-answer-sources"),
    pytest.param("studio", [
        ("studio", _DRAFT, _DISCARDED_URL),
        ("ordinary", "NO_TOOL_NEEDED", _CLASSIFIER_URL),
        ("ordinary", _CITED, _ADOPTED_URL),
    ], [], [_ADOPTED_URL], id="router-declines-adopt-ordinary-answer"),
    pytest.param("studio", [
        ("studio", _DRAFT, _DISCARDED_URL),
        ("ordinary", "invalid classification", _CLASSIFIER_URL),
        ("ordinary", _CITED, _ADOPTED_URL),
    ], [], [_ADOPTED_URL], id="discard-both-planners-adopt-inline"),
    pytest.param("router", [
        ("ordinary", "invalid classification", _CLASSIFIER_URL),
        ("studio", _CITED + "\n\n" + _READ_CALL, _ADOPTED_URL),
    ], ["Read"], [_ADOPTED_URL], id="reverse-fallback-adopts-studio"),
    pytest.param("router", [
        ("ordinary", "invalid classification", _CLASSIFIER_URL),
        ("studio", _DRAFT, _DISCARDED_URL),
        ("ordinary", _CITED, _ADOPTED_URL),
    ], [], [_ADOPTED_URL], id="reverse-fallback-discards-studio-adopts-inline"),
])
def test_ordered_planner_protocol_citations_belong_to_adopted_turn(
    tmp_path, monkeypatch, endpoint, streaming, mode, turns, tool_names, source_urls,
):
    client, pending, sockets = _planner_app(tmp_path, monkeypatch, mode, turns)
    response = client.post("/v1/" + endpoint, json=_planner_request(endpoint, streaming))
    text, tools, citations = _planner_output(response, endpoint, streaming)

    assert [tool["name"] for tool in tools] == tool_names
    assert [citation["url"] for citation in citations] == source_urls
    assert _DISCARDED_URL not in response.text
    assert _CLASSIFIER_URL not in response.text
    assert "Discarded draft" not in text
    if source_urls:
        assert "Adopted evidence [1]." in text
    else:
        assert text.strip() == "", "the two-turn chain must deliver only Read"
    assert not pending
    assert sockets and all(socket.closed for socket in sockets)


@pytest.mark.parametrize("endpoint", ["messages", "responses"])
@pytest.mark.parametrize("streaming", [False, True])
def test_adopted_studio_sources_survive_real_tool_result_continuation(
    tmp_path, monkeypatch, endpoint, streaming,
):
    final_url = "https://final.example/evidence"
    client, pending, sockets = _planner_app(tmp_path, monkeypatch, "studio", [
        ("studio", _CITED + "\n\n" + _READ_CALL, _ADOPTED_URL),
        ("studio", _CITED, final_url),
    ])
    first_request = _planner_request(endpoint, False)
    first = client.post("/v1/" + endpoint, json=first_request)
    _, calls, citations = _planner_output(first, endpoint, False)
    assert [call["name"] for call in calls] == ["Read"]
    assert [citation["url"] for citation in citations] == [_ADOPTED_URL]

    continuation = _planner_request(endpoint, streaming)
    result_text = "read-result-for-citation-continuation"
    if endpoint == "responses":
        continuation["previous_response_id"] = first.json()["id"]
        continuation["input"] = [{
            "type": "function_call_output", "call_id": calls[0]["call_id"],
            "output": result_text,
        }]
    else:
        continuation["messages"] = [
            *first_request["messages"],
            {"role": "assistant", "content": calls},
            {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": calls[0]["id"], "content": result_text,
            }]},
        ]
    final = client.post("/v1/" + endpoint, json=continuation)
    text, calls, citations = _planner_output(final, endpoint, streaming)
    assert "Adopted evidence [1]." in text
    assert calls == []
    assert [citation["url"] for citation in citations] == [final_url]
    assert _ADOPTED_URL not in final.text
    assert result_text in json.dumps(sockets[-1].invocations)
    assert not pending
    assert len(sockets) == 2 and all(socket.closed for socket in sockets)
