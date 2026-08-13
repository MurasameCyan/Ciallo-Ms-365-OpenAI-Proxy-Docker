"""tool_choice support across both API shapes.

The field was accepted and silently ignored, which is worse than not supporting
it: a client asking for tool_choice="none" still got tool_use blocks back. The
load-bearing tests here are the "none" ones, because that is the only mode we can
honour with certainty -- withholding the contract is a local decision, while the
forced modes merely instruct an upstream model that may ignore them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.models import (
    AnthropicMessage,
    AnthropicMessagesRequest,
    AnthropicToolDefinition,
    OpenAIChatRequest,
    OpenAIMessage,
    ToolDefinition,
    ToolFunction,
)
from m365_copilot_openai_proxy.translator import (
    effective_tools,
    normalize_tool_choice,
    translate_anthropic_request,
    translate_openai_request,
)

WRITE = ToolDefinition(function=ToolFunction(name="Write", description="Write a file"))
READ = ToolDefinition(function=ToolFunction(name="Read", description="Read a file"))
A_WRITE = AnthropicToolDefinition(name="Write", description="Write a file")
A_READ = AnthropicToolDefinition(name="Read", description="Read a file")


def _system(translated) -> str:
    for ctx in translated.additional_context:
        if ctx.startswith("System instructions:\n"):
            return ctx[len("System instructions:\n"):]
    return ""


def _consumer_contract(translated) -> str:
    return next(
        (ctx for ctx in translated.additional_context if ctx.startswith("Consumer tool contract:\n")),
        "",
    )


# --- normalization: both wire shapes collapse onto one mode ------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ("auto", None)),
        ("auto", ("auto", None)),
        ("none", ("none", None)),
        ("required", ("required", None)),
        ("REQUIRED", ("required", None)),            # case-insensitive
        ("Write", ("tool", "Write")),                # legacy bare name
        ({"type": "function", "function": {"name": "Write"}}, ("tool", "Write")),
        ({"type": "tool", "name": "Write"}, ("tool", "Write")),   # Anthropic
        ({"type": "any"}, ("required", None)),                    # Anthropic
        ({"type": "auto"}, ("auto", None)),
        ({"type": "none"}, ("none", None)),
        ({"function": {"name": "Write"}}, ("tool", "Write")),      # type omitted
        ({"type": "function"}, ("required", None)),                # type, no name
        ({"type": "nonsense"}, ("auto", None)),                    # unknown -> default
        (12345, ("auto", None)),                                   # wrong type
    ],
)
def test_normalize_tool_choice(raw, expected):
    mode, name, _ = normalize_tool_choice(raw)
    assert (mode, name) == expected


@pytest.mark.parametrize(
    "raw,parallel,expected",
    [
        (None, None, True),
        (None, True, True),
        (None, False, False),                                  # OpenAI spelling
        ({"type": "auto", "disable_parallel_tool_use": True}, None, False),   # Anthropic
        ({"type": "auto", "disable_parallel_tool_use": False}, None, True),
    ],
)
def test_normalize_parallel_flag(raw, parallel, expected):
    assert normalize_tool_choice(raw, parallel)[2] is expected


# --- effective_tools: the single gate every consumer reads ------------------

def test_none_yields_no_tools_at_all():
    assert effective_tools([WRITE, READ], ("none", None, True)) == []


def test_named_tool_narrows_the_list():
    assert effective_tools([WRITE, READ], ("tool", "Read", True)) == [READ]


def test_unknown_named_tool_keeps_the_list():
    # Dropping everything would look like the request carried no tools; the
    # client asked for something we cannot see, so leave the list intact.
    assert effective_tools([WRITE, READ], ("tool", "Absent", True)) == [WRITE, READ]


def test_auto_and_required_keep_every_tool():
    for mode in ("auto", "required"):
        assert effective_tools([WRITE, READ], (mode, None, True)) == [WRITE, READ]


# --- prompt side: OpenAI ----------------------------------------------------

def _openai(tool_choice=None, parallel=None, tools=(WRITE, READ)):
    return translate_openai_request(OpenAIChatRequest(
        model="m365-copilot",
        messages=[OpenAIMessage(role="user", content="写个文件")],
        tools=list(tools),
        tool_choice=tool_choice,
        parallel_tool_calls=parallel,
    ))


def test_openai_none_withholds_the_whole_tool_contract():
    system = _system(_openai(tool_choice="none"))
    assert "Write" not in system
    assert "tool_call" not in system


def test_openai_auto_still_injects_tools():
    system = _system(_openai(tool_choice="auto"))
    assert "Write" in system and "Read" in system


def test_openai_required_demands_a_call():
    system = _system(_openai(tool_choice="required"))
    assert "MUST call one of the tools" in system


def test_openai_named_tool_is_the_only_one_offered():
    system = _system(_openai(tool_choice={"type": "function", "function": {"name": "Read"}}))
    assert "MUST call the tool named Read" in system
    assert "- Write:" not in system


def test_openai_parallel_false_asks_for_one_call():
    assert "at most ONE tool_call" in _system(_openai(parallel=False))
    assert "at most ONE tool_call" not in _system(_openai())


def test_openai_consumer_contract_keeps_all_effective_tool_names():
    request = OpenAIChatRequest(
        model="copilot",
        messages=[OpenAIMessage(role="user", content="do it")],
        tools=[WRITE, READ],
        tool_choice="required",
    )

    translated = translate_openai_request(request, consumer_tool_max_chars=600)
    contract = _consumer_contract(translated)

    assert len(contract) <= 600
    assert "Write" in contract and "Read" in contract
    assert "MUST request one listed tool" in contract
    assert "You are the reasoning component" not in contract


def test_openai_consumer_named_choice_only_serializes_selected_tool():
    request = OpenAIChatRequest(
        model="copilot",
        messages=[OpenAIMessage(role="user", content="read it")],
        tools=[WRITE, READ],
        tool_choice={"type": "function", "function": {"name": "Read"}},
    )

    contract = _consumer_contract(
        translate_openai_request(request, consumer_tool_max_chars=600)
    )

    assert "Read" in contract
    assert "Write" not in contract


def test_openai_consumer_none_has_no_compact_contract():
    request = OpenAIChatRequest(
        model="copilot",
        messages=[OpenAIMessage(role="user", content="answer")],
        tools=[WRITE, READ],
        tool_choice="none",
    )

    translated = translate_openai_request(
        request,
        system_override="CUSTOM TOOL RULES",
        consumer_tool_max_chars=600,
    )

    assert not _consumer_contract(translated)
    assert not _system(translated)


def test_openai_consumer_contract_rejects_budget_too_small_for_all_tools():
    request = OpenAIChatRequest(
        model="copilot",
        messages=[OpenAIMessage(role="user", content="do it")],
        tools=[WRITE, READ],
        tool_choice="required",
    )

    with pytest.raises(
        ValueError,
        match="Consumer Copilot prompt budget cannot fit the required tool signatures",
    ):
        translate_openai_request(request, consumer_tool_max_chars=80)


def test_openai_consumer_contract_bounds_deep_schema_recursion():
    nested = {"type": "string"}
    for _ in range(1100):
        nested = {
            "type": "object",
            "properties": {"next": nested},
            "required": ["next"],
        }
    request = OpenAIChatRequest(
        model="copilot",
        messages=[OpenAIMessage(role="user", content="do it")],
        tools=[ToolDefinition(function=ToolFunction(
            name="Deep",
            parameters={
                "type": "object",
                "properties": {"root": nested},
                "required": ["root"],
            },
        ))],
    )

    contract = _consumer_contract(
        translate_openai_request(request, consumer_tool_max_chars=8000)
    )

    assert "Deep" in contract
    assert "root: object" in contract
    assert len(contract) <= 8000


# --- prompt side: Anthropic -------------------------------------------------

def _anthropic(tool_choice=None, tools=(A_WRITE, A_READ)):
    return translate_anthropic_request(AnthropicMessagesRequest(
        model="m365-copilot",
        messages=[AnthropicMessage(role="user", content="写个文件")],
        tools=list(tools),
        tool_choice=tool_choice,
    ))


def test_anthropic_none_withholds_the_whole_tool_contract():
    system = _system(_anthropic(tool_choice={"type": "none"}))
    assert "Write" not in system
    assert "tool_call" not in system


def test_anthropic_any_demands_a_call():
    assert "MUST call one of the tools" in _system(_anthropic(tool_choice={"type": "any"}))


def test_anthropic_named_tool_is_the_only_one_offered():
    system = _system(_anthropic(tool_choice={"type": "tool", "name": "Read"}))
    assert "MUST call the tool named Read" in system
    assert "- Write:" not in system


def test_anthropic_disable_parallel_asks_for_one_call():
    system = _system(_anthropic(tool_choice={"type": "auto", "disable_parallel_tool_use": True}))
    assert "at most ONE tool_call" in system


# --- response side: "none" must also disable PARSING ------------------------

def _client(tmp_path, reply):
    """App whose upstream returns `reply`, so the parse path can be driven."""
    class FakeClient:
        _tone = "Magic"

        async def chat(self, prompt, context=None, session=None, images=None):
            return reply

        async def chat_stream(self, prompt, context=None, session=None, images=None):
            yield reply

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kw: FakeClient(),
    )
    return TestClient(app)


# A reply the parser WOULD turn into a tool_call if it were allowed to look.
FENCED = '```tool_call\n{"name": "Write", "arguments": {"file_path": "/tmp/a.txt", "content": "hi"}}\n```'


def test_openai_none_suppresses_tool_calls_the_model_emitted_anyway(tmp_path):
    client = _client(tmp_path, FENCED)
    body = {
        "model": "m365-copilot",
        "messages": [{"role": "user", "content": "写个文件"}],
        "tools": [{"type": "function", "function": {"name": "Write", "description": "w"}}],
        "tool_choice": "none",
    }
    r = client.post("/v1/chat/completions", json=body, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200
    choice = r.json()["choices"][0]
    assert not choice["message"].get("tool_calls"), "tool_choice=none must not return tool_calls"
    assert choice["finish_reason"] == "stop"


def test_openai_auto_does_return_the_tool_call(tmp_path):
    # Control: proves the suppression above is the tool_choice, not a broken parse.
    client = _client(tmp_path, FENCED)
    body = {
        "model": "m365-copilot",
        "messages": [{"role": "user", "content": "写个文件"}],
        "tools": [{"type": "function", "function": {"name": "Write", "description": "w"}}],
    }
    r = client.post("/v1/chat/completions", json=body, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200
    choice = r.json()["choices"][0]
    assert [tc["function"]["name"] for tc in choice["message"]["tool_calls"]] == ["Write"]
    assert choice["finish_reason"] == "tool_calls"


def test_anthropic_none_suppresses_tool_use_the_model_emitted_anyway(tmp_path):
    client = _client(tmp_path, FENCED)
    body = {
        "model": "m365-copilot",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": "写个文件"}],
        "tools": [{"name": "Write", "description": "w", "input_schema": {"type": "object"}}],
        "tool_choice": {"type": "none"},
    }
    r = client.post("/v1/messages", json=body, headers={"x-api-key": "k"})
    assert r.status_code == 200
    d = r.json()
    assert not [b for b in d["content"] if b.get("type") == "tool_use"]
    assert d["stop_reason"] != "tool_use"


def test_anthropic_auto_does_return_the_tool_use(tmp_path):
    client = _client(tmp_path, FENCED)
    body = {
        "model": "m365-copilot",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": "写个文件"}],
        "tools": [{"name": "Write", "description": "w", "input_schema": {"type": "object"}}],
    }
    r = client.post("/v1/messages", json=body, headers={"x-api-key": "k"})
    assert r.status_code == 200
    d = r.json()
    assert [b["name"] for b in d["content"] if b.get("type") == "tool_use"] == ["Write"]
    assert d["stop_reason"] == "tool_use"
