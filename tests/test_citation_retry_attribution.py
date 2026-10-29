"""A retry is a SEPARATE upstream turn; its sources belong to its own text.

Both protocol-native citation paths used to share one ``collected_sources``
list across the original turn and its retry. That produced two defects at
once, and neither is visible without looking at the citations:

* the retry's text was thrown away (it produced no usable tool call), but its
  URLs had already replaced the kept reply's -- so every ``[n]`` pointed into
  a turn the reader never saw;
* the retry RAISED, and the kept reply was left with no sources at all,
  because the list had been cleared before the retry ran.

The rule these pin: sources are adopted only in the same step as the text
they belong to. The corrective retry is the path where a retry can be
DISCARDED while the first answer is kept, so that is what most of these use.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from m365_copilot_openai_proxy.response_helpers import _responses_stream_with_tools
from m365_copilot_openai_proxy.routes_api_messages import _anthropic_stream_with_tools
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotError

FIRST_SOURCES = [{"title": "first", "url": "https://first.example", "ref_key": "1-aaaaaa"}]
RETRY_SOURCES = [{"title": "retry", "url": "https://retry.example", "ref_key": "1-bbbbbb"}]

# A hosted file link with no tool_call: what triggers the corrective retry.
CLAIM = "已生成 demo.py: https://x.example/demo.py [1]"
TOOL_CALL = '```tool_call\n{"name":"Read","arguments":{"file_path":"S:/a.txt"}}\n```'


def _fill(sources_out, values):
    if sources_out is None:
        return
    sources_out.clear()
    sources_out.extend(dict(value) for value in values)


class _ClaimingClient:
    """First turn claims a file it never wrote; the retry answers ``retry_text``.

    ``retry_error`` instead makes the retry raise, which is the "upstream broke
    mid-retry" case.
    """

    def __init__(self, *, retry_text: str = "retry prose, still no tool call [1]",
                 retry_error: Exception | None = None):
        self.retry_text = retry_text
        self.retry_error = retry_error
        self.prompts: list[str] = []

    def _note(self, prompt) -> int:
        self.prompts.append(prompt)
        return len(self.prompts)

    async def chat_stream(self, prompt, additional_context, session=None, images=None, *, sources_out=None):
        if self._note(prompt) == 1:
            _fill(sources_out, FIRST_SOURCES)
            yield CLAIM
            return
        if self.retry_error is not None:
            raise self.retry_error
        _fill(sources_out, RETRY_SOURCES)
        yield self.retry_text


class _ClaimingChatClient(_ClaimingClient):
    """The non-streaming protocol shape (``chat`` instead of ``chat_stream``)."""

    async def chat(self, prompt, additional_context, session=None, images=None, *, sources_out=None):
        if self._note(prompt) == 1:
            _fill(sources_out, FIRST_SOURCES)
            return CLAIM
        if self.retry_error is not None:
            raise self.retry_error
        _fill(sources_out, RETRY_SOURCES)
        return self.retry_text


def _events(gen) -> list[dict]:
    async def run():
        return [chunk async for chunk in gen]

    events = []
    for chunk in asyncio.run(run()):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def _responses_annotations(events: list[dict]) -> list[dict]:
    completed = [e for e in events if e["type"] == "response.completed"]
    assert completed, [e["type"] for e in events]
    annotations = []
    for item in completed[-1]["response"]["output"]:
        if item["type"] != "message":
            continue
        for part in item["content"]:
            annotations.extend(part.get("annotations") or [])
    return annotations


def _anthropic_citations(events: list[dict]) -> list[dict]:
    return [
        event["delta"]["citation"]
        for event in events
        if event.get("type") == "content_block_delta"
        and event["delta"].get("type") == "citations_delta"
    ]


def _responses_stream(client):
    return _responses_stream_with_tools(
        "m365-copilot", client, "write demo.py", [], tool_names={"Read"},
    )


def _messages_stream(client):
    return _anthropic_stream_with_tools(
        "m365-copilot", client, "write demo.py", [], tool_names={"Read"},
    )


# --- the retry's text is NOT adopted ---------------------------------------

def test_thrown_away_retry_does_not_re_point_the_kept_reply():
    """The retry produced no tool call, so its text is dropped -- and its URLs
    have to go with it. Otherwise the kept reply's ``[1]`` cites a turn the
    reader never saw."""
    client = _ClaimingClient()
    annotations = _responses_annotations(_events(_responses_stream(client)))

    assert len(client.prompts) == 2, "the corrective retry did not fire"
    assert [a["url"] for a in annotations] == ["https://first.example"]


def test_thrown_away_retry_does_not_re_point_the_kept_reply_in_messages():
    client = _ClaimingClient()
    citations = _anthropic_citations(_events(_messages_stream(client)))

    assert len(client.prompts) == 2
    assert [c["url"] for c in citations] == ["https://first.example"]


# --- the retry RAISES: only the NON-streaming paths keep the reply --------
#
# A raising corrective retry in the streaming paths is not a citation question:
# it fails the turn (see `test_responses_stream_failed`). The quote from the
# review -- "the kept reply lost all its sources" -- is about the non-streaming
# retries, which swallow the error and keep the first answer.

def _app_with(tmp_path, upstream):
    from fastapi.testclient import TestClient

    from m365_copilot_openai_proxy.app import create_app
    from m365_copilot_openai_proxy.config import Settings

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **_kwargs: upstream,
    )
    app.state.tool_planning_mode = "native"
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer k"
    return client


READ_SCHEMA = {
    "type": "object",
    "properties": {"file_path": {"type": "string"}},
    "required": ["file_path"],
}


@pytest.mark.parametrize("endpoint", ["messages", "responses"])
def test_a_raising_non_stream_retry_keeps_the_kept_reply_citations(tmp_path, endpoint):
    """Clearing the shared list before the retry ran is what left the kept
    reply with no sources when the retry threw."""
    client = _app_with(tmp_path, _ClaimingChatClient(
        retry_error=SubstrateCopilotError("upstream broke"),
    ))
    body = {"model": "m365-copilot", "stream": False}
    if endpoint == "responses":
        body["input"] = "write demo.py"
        body["tools"] = [{"type": "function", "name": "Read", "parameters": READ_SCHEMA}]
    else:
        body["messages"] = [{"role": "user", "content": "write demo.py"}]
        body["max_tokens"] = 256
        body["tools"] = [{
            "name": "Read", "description": "read", "input_schema": READ_SCHEMA,
        }]

    response = client.post("/v1/" + endpoint, json=body)

    assert response.status_code == 200, response.text
    assert "demo.py" in response.text
    # The kept reply's citation survives the retry that threw.
    body_json = response.json()
    if endpoint == "responses":
        citations = [
            annotation
            for item in body_json["output"]
            if item.get("type") == "message"
            for part in item.get("content", [])
            for annotation in (part.get("annotations") or [])
        ]
    else:
        # Anthropic hangs citations on the text block that carries the prose.
        citations = [
            citation
            for block in body_json["content"]
            for citation in (block.get("citations") or [])
        ]
    assert [c["url"] for c in citations] == ["https://first.example"], response.text


# --- the retry's text IS adopted ------------------------------------------



def test_adopted_retry_takes_its_sources_with_its_text():
    """The other half of the invariant: when the retry DOES supply the tool
    call, its text and its sources change hands together."""
    client = _ClaimingClient(retry_text="好的。\n\n" + TOOL_CALL)
    events = _events(_responses_stream(client))

    completed = [e for e in events if e["type"] == "response.completed"]
    assert completed, [e["type"] for e in events]
    output = completed[-1]["response"]["output"]
    assert [item["name"] for item in output if item["type"] == "function_call"] == ["Read"]

    annotations = _responses_annotations(events)
    assert [a["url"] for a in annotations] == ["https://retry.example"]


def test_discarded_retry_leaves_the_kept_answer_alone():
    """Nothing of the discarded retry may reach the reader: not its text, not
    its URLs."""
    client = _ClaimingClient(retry_text="重试的正文不应该出现 [1]")
    events = _events(_responses_stream(client))

    text = "".join(
        part["text"]
        for event in events
        if event["type"] == "response.output_text.delta"
        for part in [{"text": event["delta"]}]
    )
    assert "重试的正文" not in text
    assert "demo.py" in text
