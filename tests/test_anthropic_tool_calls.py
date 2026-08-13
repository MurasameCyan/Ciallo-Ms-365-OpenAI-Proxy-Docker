from __future__ import annotations

import asyncio
import json

import pytest

from m365_copilot_openai_proxy.models import (
    AnthropicMessage,
    AnthropicMessagesRequest,
    AnthropicToolDefinition,
    ContentPart,
)
from m365_copilot_openai_proxy.routes_api_messages import (
    _anthropic_stream_with_tools,
    _resolve_tool_calls,
    _tool_use_blocks,
)
from m365_copilot_openai_proxy.translator import translate_anthropic_request


WRITE_TOOL = AnthropicToolDefinition(
    name="Write",
    description="Write a file",
    input_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "target path"},
            "content": {"type": "string", "description": "file body"},
        },
        "required": ["file_path", "content"],
    },
)


def _system_context(translated) -> str:
    for ctx in translated.additional_context:
        if ctx.startswith("System instructions:\n"):
            return ctx[len("System instructions:\n"):]
    return ""


def _transcript(translated) -> str:
    for ctx in translated.additional_context:
        if ctx.startswith("Prior conversation transcript:\n"):
            return ctx[len("Prior conversation transcript:\n"):]
    return ""


def _consumer_tool_contract(translated) -> str:
    for ctx in translated.additional_context:
        if ctx.startswith("Consumer tool contract:\n"):
            return ctx
    return ""


# --- request side: the model has to be TOLD about the tools ----------------

def test_anthropic_tools_inject_tool_call_contract():
    """Anthropic keeps name/description/input_schema flat, so without adapting
    them to the OpenAI shape the tool prompt was never rendered and the model
    never learned the ```tool_call``` contract."""
    request = AnthropicMessagesRequest(
        model="claude",
        tools=[WRITE_TOOL],
        messages=[AnthropicMessage(role="user", content="写个文件")],
    )

    system = _system_context(translate_anthropic_request(request))

    assert "tool_call" in system
    assert "- Write: Write a file" in system
    assert "file_path" in system and "(required)" in system


def test_anthropic_without_tools_injects_no_tool_prompt():
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[AnthropicMessage(role="user", content="hi")],
    )

    assert "tool_call" not in _system_context(translate_anthropic_request(request))


def test_anthropic_consumer_without_tools_does_not_inject_tool_system_override():
    request = AnthropicMessagesRequest(
        model="copilot",
        messages=[AnthropicMessage(role="user", content="hi")],
    )

    translated = translate_anthropic_request(
        request,
        system_override="CUSTOM TOOL RULES",
        consumer_tool_max_chars=700,
    )

    assert not _system_context(translated)


def test_anthropic_tool_system_override_is_honoured():
    request = AnthropicMessagesRequest(
        model="claude",
        tools=[WRITE_TOOL],
        messages=[AnthropicMessage(role="user", content="hi")],
    )

    system = _system_context(translate_anthropic_request(request, system_override="CUSTOM RULES"))

    assert system.startswith("CUSTOM RULES")
    assert "- Write: Write a file" in system


def test_anthropic_consumer_tool_contract_keeps_signature_without_default_examples():
    request = AnthropicMessagesRequest(
        model="copilot",
        tools=[WRITE_TOOL],
        messages=[AnthropicMessage(role="user", content="写个文件")],
    )

    translated = translate_anthropic_request(
        request,
        consumer_tool_max_chars=700,
    )
    contract = _consumer_tool_contract(translated)

    assert len(contract) <= 700
    assert "Write" in contract
    assert "file_path: string required" in contract
    assert "content: string required" in contract
    assert "You are the reasoning component" not in contract
    assert "Example:" not in contract
    assert "[FORMAT]" not in contract


def test_anthropic_consumer_custom_tool_rules_remain_system_context():
    request = AnthropicMessagesRequest(
        model="copilot",
        tools=[WRITE_TOOL],
        messages=[AnthropicMessage(role="user", content="hi")],
    )

    translated = translate_anthropic_request(
        request,
        system_override="CUSTOM CONSUMER RULE",
        consumer_tool_max_chars=700,
    )

    assert "CUSTOM CONSUMER RULE" in _system_context(translated)
    assert _consumer_tool_contract(translated)


# --- request side: the agentic loop carries state in content blocks --------

def test_anthropic_tool_result_only_turn_synthesizes_continuation_prompt():
    """The host answers a tool_use with a user message holding only a tool_result
    block. flatten_content sees no text, so this used to raise 'a final user
    message is required' and the loop could never continue."""
    request = AnthropicMessagesRequest(
        model="claude",
        tools=[WRITE_TOOL],
        messages=[
            AnthropicMessage(role="user", content="写个文件"),
            AnthropicMessage(
                role="assistant",
                content=[ContentPart.model_validate({
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Write",
                    "input": {"file_path": "S:/a.py", "content": "print(1)"},
                })],
            ),
            AnthropicMessage(
                role="user",
                content=[ContentPart.model_validate({
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "File written successfully",
                })],
            ),
        ],
    )

    translated = translate_anthropic_request(request)

    assert "Continue the task" in translated.prompt
    transcript = _transcript(translated)
    assert "Assistant called tool: Write(" in transcript
    assert "S:/a.py" in transcript
    assert "File written successfully" in transcript


def test_anthropic_tool_result_block_array_is_flattened():
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[
            AnthropicMessage(role="user", content="go"),
            AnthropicMessage(
                role="user",
                content=[ContentPart.model_validate({
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": [{"type": "text", "text": "line one"}],
                })],
            ),
        ],
    )

    assert "line one" in _transcript(translate_anthropic_request(request))


def test_anthropic_tool_error_is_labelled():
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[
            AnthropicMessage(role="user", content="go"),
            AnthropicMessage(
                role="user",
                content=[ContentPart.model_validate({
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "permission denied",
                    "is_error": True,
                })],
            ),
        ],
    )

    assert "Tool error" in _transcript(translate_anthropic_request(request))


def test_anthropic_still_rejects_assistant_final_message():
    request = AnthropicMessagesRequest(
        model="claude",
        messages=[AnthropicMessage(role="assistant", content="I am last")],
    )

    with pytest.raises(ValueError):
        translate_anthropic_request(request)


# --- response side: tool_call text has to become tool_use blocks -----------

_WRITE_REPLY = (
    "好的，我来写。\n\n```tool_call\n"
    '{"name": "Write", "arguments": {"file_path": "S:/a.py", "content": "print(1)"}}\n'
    "```"
)


def test_tool_use_blocks_decode_arguments_into_input_object():
    """Anthropic carries arguments as a decoded object, not OpenAI's JSON string."""
    calls = _resolve_tool_calls(_WRITE_REPLY, {"Write"}, read_only_guard=False)
    blocks = _tool_use_blocks(calls)

    assert len(blocks) == 1
    assert blocks[0]["type"] == "tool_use"
    assert blocks[0]["name"] == "Write"
    assert blocks[0]["input"] == {"file_path": "S:/a.py", "content": "print(1)"}
    assert blocks[0]["id"]


def test_resolve_tool_calls_needs_declared_tools():
    assert _resolve_tool_calls(_WRITE_REPLY, set(), read_only_guard=False) == []


def test_resolve_tool_calls_read_only_guard_blocks_write():
    assert _resolve_tool_calls(_WRITE_REPLY, {"Write"}, read_only_guard=True) == []


class _ReplyClient:
    def __init__(self, text: str):
        self._text = text

    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        yield self._text


def _events(gen) -> list[dict]:
    async def run():
        return [chunk async for chunk in gen]

    out = []
    for chunk in asyncio.run(run()):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[len("data: "):]))
    return out


def test_anthropic_stream_emits_tool_use_content_block():
    events = _events(_anthropic_stream_with_tools(
        "m365-copilot",
        _ReplyClient(_WRITE_REPLY),
        "写个文件",
        [],
        tool_names={"Write"},
    ))

    starts = [e for e in events if e.get("type") == "content_block_start"]
    assert [s["content_block"]["type"] for s in starts] == ["text", "tool_use"]
    assert starts[1]["content_block"]["name"] == "Write"

    payloads = [
        e["delta"]["partial_json"]
        for e in events
        if e.get("type") == "content_block_delta" and e["delta"].get("type") == "input_json_delta"
    ]
    assert json.loads(payloads[0]) == {"file_path": "S:/a.py", "content": "print(1)"}

    deltas = [e for e in events if e.get("type") == "message_delta"]
    assert deltas[0]["delta"]["stop_reason"] == "tool_use"

    # The tool_call fence itself must not leak into the text block.
    text = "".join(
        e["delta"]["text"]
        for e in events
        if e.get("type") == "content_block_delta" and e["delta"].get("type") == "text_delta"
    )
    assert "tool_call" not in text
    assert "好的，我来写。" in text


def test_anthropic_stream_without_tool_call_ends_with_end_turn():
    events = _events(_anthropic_stream_with_tools(
        "m365-copilot",
        _ReplyClient("就是一段普通回答"),
        "hi",
        [],
        tool_names={"Write"},
    ))

    assert [e["content_block"]["type"] for e in events if e.get("type") == "content_block_start"] == ["text"]
    assert [e for e in events if e.get("type") == "message_delta"][0]["delta"]["stop_reason"] == "end_turn"
    text = "".join(
        e["delta"]["text"]
        for e in events
        if e.get("type") == "content_block_delta" and e["delta"].get("type") == "text_delta"
    )
    assert text == "就是一段普通回答"
