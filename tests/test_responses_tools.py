from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy import response_helpers, routes_api_responses
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.models import OpenAIResponsesRequest
from m365_copilot_openai_proxy.session_helpers import (
    _decode_responses_session_id,
    _encode_responses_session_id,
)
from m365_copilot_openai_proxy.session_store import (
    PersistentSession,
    PersistentSessionStore,
)
from m365_copilot_openai_proxy.substrate_client import (
    SubstrateCopilotError,
    SubstrateThrottled,
)
from m365_copilot_openai_proxy.translator import translate_responses_request


READ_TOOL = {
    "type": "function",
    "name": "Read",
    "description": "Read a file",
    "parameters": {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
    },
    "strict": False,
}

WRITE_TOOL = {
    "type": "function",
    "name": "Write",
    "description": "Write a file",
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["file_path", "content"],
    },
    "strict": False,
}

FILES_NAMESPACE_TOOL = {
    "type": "namespace",
    "name": "filesystem",
    "description": "Local filesystem inspection tools",
    "tools": [READ_TOOL],
}

READ_CALL = (
    "I'll inspect it.\n\n```tool_call\n"
    '{"name":"Read","arguments":{"file_path":"S:/repo/README.md"}}\n'
    "```"
)

INVALID_READ_CALL = (
    '```tool_call\n{"name":"Read","arguments":"not-json"}\n```'
)

NON_OBJECT_READ_CALL = (
    '```tool_call\n{"name":"Read","arguments":[1,2]}\n```'
)

INVALID_STRICT_READ_CALL = (
    '```tool_call\n{"name":"Read","arguments":{"file_path":123}}\n```'
)

PARALLEL_READ_CALLS = (
    '```tool_call\n{"name":"Read","arguments":{"file_path":"a.txt"}}\n```\n'
    '```tool_call\n{"name":"Read","arguments":{"file_path":"b.txt"}}\n```'
)


def _context(translated, prefix: str) -> str:
    return next(
        (part for part in translated.additional_context if part.startswith(prefix)),
        "",
    )


class _ReplyClient:
    _tone = "Magic"

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[tuple[str, list[str]]] = []

    async def chat(self, prompt, additional_context, session=None, images=None):
        self.calls.append((prompt, additional_context))
        if session is not None:
            session.reserve_turn()
        return self.reply

    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        self.calls.append((prompt, additional_context))
        if session is not None:
            session.reserve_turn()
        yield self.reply


class _FailingStreamClient(_ReplyClient):
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        self.calls.append((prompt, additional_context))
        if session is not None:
            session.reserve_turn()
        raise SubstrateCopilotError(self.reply)
        yield ""  # pragma: no cover - marks this as an async generator


class _ThrottledStreamClient(_ReplyClient):
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        self.calls.append((prompt, additional_context))
        raise SubstrateThrottled("upstream result: Throttled")
        yield ""  # pragma: no cover - marks this as an async generator


class _FailingClient(_ReplyClient):
    async def chat(self, prompt, additional_context, session=None, images=None):
        self.calls.append((prompt, additional_context))
        if session is not None:
            session.reserve_turn()
        raise SubstrateCopilotError(self.reply)


class _RuntimeFailingClient(_ReplyClient):
    async def chat(self, prompt, additional_context, session=None, images=None):
        self.calls.append((prompt, additional_context))
        if session is not None:
            session.reserve_turn()
        raise RuntimeError(self.reply)


class _RetryFailingStreamClient(_ReplyClient):
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        self.calls.append((prompt, additional_context))
        if session is not None:
            session.reserve_turn()
        if len(self.calls) == 1:
            yield "plain prose"
            return
        raise SubstrateCopilotError(self.reply)
        yield ""  # pragma: no cover - marks this as an async generator


class _ImageReplyClient(_ReplyClient):
    def __init__(self, reply: str):
        super().__init__(reply)
        self.image_calls: list[list | None] = []

    async def chat(self, prompt, additional_context, session=None, images=None):
        self.calls.append((prompt, additional_context))
        self.image_calls.append(images)
        if session is not None:
            session.reserve_turn()
        return self.reply


class _RepeatedReplyStreamClient(_ReplyClient):
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        self.calls.append((prompt, additional_context))
        if session is not None:
            session.reserve_turn()
        yield self.reply
        yield self.reply


def _app_client(tmp_path, reply: str, client_type=_ReplyClient):
    made: list[_ReplyClient] = []

    def factory(**kwargs):
        client = client_type(reply)
        made.append(client)
        return client

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=factory,
    )
    return app, TestClient(app), made


def _post(client: TestClient, body: dict):
    return client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer k"},
        json={"model": "m365-copilot", **body},
    )


def _events(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _event_names(response) -> list[str]:
    return [
        line.removeprefix("event: ")
        for line in response.text.splitlines()
        if line.startswith("event: ")
    ]


def test_responses_flat_function_tool_injects_existing_tool_contract():
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": "read the file",
        "tools": [READ_TOOL],
        "tool_choice": "required",
    })

    translated = translate_responses_request(request)
    system = _context(translated, "System instructions:\n")

    assert "- Read:" in system
    assert "file_path" in system
    assert "MUST call one of the tools" in system


def test_responses_consumer_function_tool_uses_compact_contract():
    request = OpenAIResponsesRequest.model_validate({
        "model": "copilot-reasoning",
        "input": "read the file",
        "tools": [READ_TOOL],
    })

    translated = translate_responses_request(
        request,
        consumer_tool_max_chars=600,
    )
    contract = _context(translated, "Consumer tool contract:\n")

    assert "Read(file_path: string required)" in contract
    assert len(contract) <= 600


def test_responses_flat_named_tool_choice_selects_only_named_tool():
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": "read the file",
        "tools": [READ_TOOL, WRITE_TOOL],
        "tool_choice": {"type": "function", "name": "Read"},
    })

    translated = translate_responses_request(request)
    system = _context(translated, "System instructions:\n")

    assert "- Read:" in system
    assert "- Write:" not in system
    assert "MUST call the tool named Read" in system


@pytest.mark.parametrize("tool_choice,tools,error", [
    (
        {"type": "function", "name": "Missing"},
        [READ_TOOL],
        "is not declared",
    ),
    (
        {"type": "web_search_preview"},
        [READ_TOOL],
        "Unsupported Responses tool_choice",
    ),
    (
        {
            "type": "allowed_tools",
            "mode": "auto",
            "tools": [{"type": "function", "name": "Read"}],
        },
        [READ_TOOL, WRITE_TOOL],
        "Unsupported Responses tool_choice",
    ),
    (
        "required",
        [],
        "requires at least one function tool",
    ),
])
def test_responses_rejects_invalid_tool_choice_before_upstream_call(
    tmp_path, tool_choice, tools, error,
):
    _app, client, made = _app_client(tmp_path, "unused")

    response = _post(client, {
        "input": "use the selected tool",
        "tools": tools,
        "tool_choice": tool_choice,
    })

    assert response.status_code == 400
    assert error in response.text
    assert not made or made[-1].calls == []


def test_responses_rejects_non_string_named_tool_choice_as_400(tmp_path):
    app, _client, made = _app_client(tmp_path, "unused")
    client = TestClient(app, raise_server_exceptions=False)

    response = _post(client, {
        "input": "use the selected tool",
        "tools": [READ_TOOL],
        "tool_choice": {"type": "function", "name": 123},
    })

    assert response.status_code == 400
    assert "function name" in response.text
    assert not made or made[-1].calls == []


def test_responses_rejects_malformed_json_as_400(tmp_path):
    app, _client, made = _app_client(tmp_path, "unused")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer k", "Content-Type": "application/json"},
        content="{\"model\":",
    )

    assert response.status_code == 400
    assert not made or made[-1].calls == []


@pytest.mark.parametrize("tool,error", [
    (
        {
            **READ_TOOL,
            "parameters": {
                "type": "object",
                "properties": {"file_path": "string"},
            },
        },
        "property schemas must be objects",
    ),
    (
        {**READ_TOOL, "strict": "true"},
        "strict must be a boolean",
    ),
])
def test_responses_rejects_unsupported_function_schema_before_upstream_call(
    tmp_path, tool, error,
):
    app, _client, made = _app_client(tmp_path, "unused")
    client = TestClient(app, raise_server_exceptions=False)

    response = _post(client, {
        "input": "use the tool",
        "tools": [tool],
    })

    assert response.status_code == 400
    assert error in response.text
    assert not made or made[-1].calls == []


def test_responses_accepts_schema_valid_strict_function_tool(tmp_path):
    """SDK/Codex strict tools remain usable after local schema validation."""
    _app, client, made = _app_client(tmp_path, READ_CALL)

    response = _post(client, {
        "input": "read README",
        "tools": [{**READ_TOOL, "strict": True}],
    })

    assert response.status_code == 200
    assert any(item["type"] == "function_call" for item in response.json()["output"])
    assert made[-1].calls


def test_responses_accepts_null_strict_as_default_non_strict(tmp_path):
    _app, client, made = _app_client(tmp_path, READ_CALL)

    response = _post(client, {
        "input": "read README",
        "tools": [{**READ_TOOL, "strict": None}],
    })

    assert response.status_code == 200
    assert any(item["type"] == "function_call" for item in response.json()["output"])
    assert made[-1].calls


def test_responses_accepts_locally_resolvable_strict_function_refs(tmp_path):
    _app, client, made = _app_client(tmp_path, READ_CALL)
    tool = {
        **READ_TOOL,
        "strict": True,
        "parameters": {
            "type": "object",
            "$defs": {"path": {"type": "string"}},
            "properties": {"file_path": {"$ref": "#/$defs/path"}},
            "required": ["file_path"],
        },
    }

    response = _post(client, {
        "input": "read README",
        "tools": [tool],
    })

    assert response.status_code == 200
    assert any(item["type"] == "function_call" for item in response.json()["output"])
    assert made[-1].calls


def test_responses_local_ref_types_are_preserved_in_tool_prompts():
    tool = {
        **READ_TOOL,
        "strict": True,
        "parameters": {
            "type": "object",
            "$defs": {"path": {"type": "string"}},
            "properties": {"file_path": {"$ref": "#/$defs/path"}},
            "required": ["file_path"],
        },
    }

    m365 = translate_responses_request(OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": "read README",
        "tools": [tool],
    }))
    consumer = translate_responses_request(
        OpenAIResponsesRequest.model_validate({
            "model": "copilot-reasoning",
            "input": "read README",
            "tools": [tool],
        }),
        consumer_tool_max_chars=600,
    )

    assert "file_path: string (required)" in _context(
        m365,
        "System instructions:\n",
    )
    assert "Read(file_path: string required)" in _context(
        consumer,
        "Consumer tool contract:\n",
    )


def test_responses_root_local_ref_is_preserved_in_tool_prompts():
    tool = {
        **READ_TOOL,
        "strict": True,
        "parameters": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "#/$defs/Args",
            "$defs": {
                "Args": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            },
            "additionalProperties": False,
        },
    }
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": "read README",
        "tools": [tool],
    })

    m365 = translate_responses_request(request)
    consumer = translate_responses_request(request, consumer_tool_max_chars=600)

    assert "file_path: string (required)" in _context(
        m365,
        "System instructions:\n",
    )
    assert "Read(file_path: string required)" in _context(
        consumer,
        "Consumer tool contract:\n",
    )


def test_responses_ref_sibling_object_fields_are_merged_in_tool_prompts():
    tool = {
        "type": "function",
        "name": "Read",
        "parameters": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "#/$defs/Args",
            "$defs": {
                "Args": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            },
            "properties": {"mode": {"type": "string"}},
            "required": ["mode"],
        },
        "strict": True,
    }
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": "read README",
        "tools": [tool],
    })

    m365 = _context(
        translate_responses_request(request),
        "System instructions:\n",
    )
    consumer = _context(
        translate_responses_request(request, consumer_tool_max_chars=600),
        "Consumer tool contract:\n",
    )

    assert "file_path: string (required)" in m365
    assert "mode: string (required)" in m365
    assert "file_path: string required" in consumer
    assert "mode: string required" in consumer


def test_responses_ref_sibling_same_property_keywords_are_merged_in_tool_prompts():
    tool = {
        "type": "function",
        "name": "Read",
        "parameters": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "#/$defs/Args",
            "$defs": {
                "Args": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            },
            "properties": {
                "file_path": {"description": "Path to inspect"},
            },
        },
        "strict": True,
    }
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": "read README",
        "tools": [tool],
    })

    m365 = _context(
        translate_responses_request(request),
        "System instructions:\n",
    )
    consumer = _context(
        translate_responses_request(request, consumer_tool_max_chars=600),
        "Consumer tool contract:\n",
    )

    assert "file_path: string (required) — Path to inspect" in m365
    assert "Read(file_path: string required)" in consumer


@pytest.mark.parametrize(
    ("dialect", "defs_key", "anchor_keyword"),
    [
        (
            "https://json-schema.org/draft/2020-12/schema",
            "$defs",
            "$anchor",
        ),
        (
            "https://json-schema.org/draft/2020-12/schema",
            "$defs",
            "$dynamicAnchor",
        ),
        (
            "http://json-schema.org/draft-07/schema#",
            "definitions",
            "$id",
        ),
        (
            "http://json-schema.org/draft-06/schema#",
            "definitions",
            "$id",
        ),
        (
            "http://json-schema.org/draft-04/schema#",
            "definitions",
            "id",
        ),
    ],
)
def test_responses_local_anchor_ref_types_are_preserved_in_tool_prompts(
    dialect,
    defs_key,
    anchor_keyword,
):
    tool = {
        "type": "function",
        "name": "Read",
        "parameters": {
            "$schema": dialect,
            defs_key: {
                "path": {
                    anchor_keyword: (
                        "path"
                        if anchor_keyword in {"$anchor", "$dynamicAnchor"}
                        else "#path"
                    ),
                    "type": "string",
                },
            },
            "type": "object",
            "properties": {"file_path": {"$ref": "#path"}},
            "required": ["file_path"],
        },
        "strict": True,
    }
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": "read README",
        "tools": [tool],
    })

    m365 = _context(
        translate_responses_request(request),
        "System instructions:\n",
    )
    consumer = _context(
        translate_responses_request(request, consumer_tool_max_chars=600),
        "Consumer tool contract:\n",
    )

    assert "file_path: string (required)" in m365
    assert "Read(file_path: string required)" in consumer


def test_responses_boolean_property_schemas_are_preserved_in_tool_prompts():
    tool = {
        "type": "function",
        "name": "Check",
        "parameters": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"allowed": True, "blocked": False},
        },
        "strict": True,
    }
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": "check values",
        "tools": [tool],
    })

    m365 = translate_responses_request(request)
    consumer = translate_responses_request(request, consumer_tool_max_chars=600)

    assert "allowed: any" in _context(m365, "System instructions:\n")
    assert "blocked: never" in _context(m365, "System instructions:\n")
    assert "allowed: any" in _context(consumer, "Consumer tool contract:\n")
    assert "blocked: never" in _context(consumer, "Consumer tool contract:\n")


@pytest.mark.parametrize(
    ("dialect", "defs_key", "expect_sibling"),
    [
        ("https://json-schema.org/draft/2020-12/schema", "$defs", True),
        ("http://json-schema.org/draft-04/schema#", "definitions", False),
    ],
)
def test_responses_ref_sibling_prompt_matches_declared_dialect(
    dialect,
    defs_key,
    expect_sibling,
):
    tool = {
        "type": "function",
        "name": "Read",
        "parameters": {
            "$schema": dialect,
            "type": "object",
            defs_key: {"path": {"type": "string"}},
            "properties": {
                "file_path": {
                    "$ref": f"#/{defs_key}/path",
                    "enum": ["README.md"],
                },
            },
        },
        "strict": True,
    }
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": "read README",
        "tools": [tool],
    })

    translated = translate_responses_request(request)
    prompt = _context(translated, "System instructions:\n")

    assert ('enum=["README.md"]' in prompt) is expect_sibling


@pytest.mark.parametrize("value,expected_call", [(1, True), (0, False)])
def test_responses_honors_declared_strict_schema_dialect(
    tmp_path,
    value,
    expected_call,
):
    reply = (
        '```tool_call\n{"name":"Check","arguments":{"value":'
        f"{value}"
        '}}\n```'
    )
    _app, client, made = _app_client(tmp_path, reply)
    tool = {
        "type": "function",
        "name": "Check",
        "parameters": {
            "$schema": "http://json-schema.org/draft-04/schema#",
            "type": "object",
            "properties": {
                "value": {
                    "type": "number",
                    "minimum": 0,
                    "exclusiveMinimum": True,
                },
            },
            "required": ["value"],
        },
        "strict": True,
    }

    response = _post(client, {
        "input": "check the value",
        "tools": [tool],
    })

    assert response.status_code == 200
    assert any(
        item["type"] == "function_call"
        for item in response.json()["output"]
    ) is expected_call
    assert made[-1].calls


def test_responses_rejects_unknown_strict_schema_dialect_before_upstream(tmp_path):
    _app, client, made = _app_client(tmp_path, "unused")
    tool = {
        **READ_TOOL,
        "strict": True,
        "parameters": {
            "$schema": "https://example.invalid/json-schema",
            "type": "object",
        },
    }

    response = _post(client, {
        "input": "read README",
        "tools": [tool],
    })

    assert response.status_code == 400
    assert "JSON Schema dialect" in response.text
    assert not made or made[-1].calls == []


def test_responses_accepts_resolvable_strict_dynamic_ref(tmp_path):
    _app, client, made = _app_client(tmp_path, READ_CALL)
    tool = {
        **READ_TOOL,
        "strict": True,
        "parameters": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$dynamicAnchor": "args",
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "nested": {"$dynamicRef": "#args"},
            },
            "required": ["file_path"],
        },
    }

    response = _post(client, {
        "input": "read README",
        "tools": [tool],
    })

    assert response.status_code == 200
    assert any(item["type"] == "function_call" for item in response.json()["output"])
    assert made[-1].calls


@pytest.mark.parametrize("stream", [False, True])
def test_responses_recursive_strict_schema_does_not_crash_runtime_validation(
    tmp_path,
    stream,
):
    _app, client, _made = _app_client(
        tmp_path,
        '```tool_call\n{"name":"Loop","arguments":{}}\n```',
    )
    tool = {
        "type": "function",
        "name": "Loop",
        "parameters": {"$ref": "#"},
        "strict": True,
    }

    response = _post(client, {
        "input": "use the tool",
        "stream": stream,
        "tools": [tool],
    })

    assert response.status_code == 200
    if stream:
        assert "response.function_call_arguments" not in response.text
        assert "response.completed" in response.text
    else:
        assert not any(
            item["type"] == "function_call"
            for item in response.json()["output"]
        )


def test_responses_deep_strict_schema_is_rejected_without_server_error(tmp_path):
    app, _client, made = _app_client(tmp_path, "unused")
    client = TestClient(app, raise_server_exceptions=False)
    parameters = {"type": "object"}
    for _ in range(100):
        parameters = {
            "type": "object",
            "properties": {"child": parameters},
        }

    response = _post(client, {
        "input": "use the tool",
        "tools": [{
            "type": "function",
            "name": "Deep",
            "parameters": parameters,
            "strict": True,
        }],
    })

    assert response.status_code == 400
    assert "too deeply nested" in response.text
    assert not made or made[-1].calls == []


@pytest.mark.parametrize(
    ("ref_keyword", "ref"),
    [
        ("$ref", "#/$defs/missing"),
        ("$ref", "https://example.invalid/function-schema.json"),
        ("$dynamicRef", "#missing"),
        ("$dynamicRef", "https://example.invalid/function-schema.json"),
    ],
)
def test_responses_rejects_unresolvable_strict_function_refs_before_upstream(
    tmp_path,
    ref_keyword,
    ref,
):
    app, _client, made = _app_client(tmp_path, READ_CALL)
    client = TestClient(app, raise_server_exceptions=False)
    tool = {
        **READ_TOOL,
        "strict": True,
        "parameters": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"file_path": {ref_keyword: ref}},
        },
    }

    response = _post(client, {
        "input": "read README",
        "tools": [tool],
    })

    assert response.status_code == 400
    assert "resolvable" in response.text
    assert not made or made[-1].calls == []


@pytest.mark.parametrize("stream", [False, True])
def test_responses_strict_function_tool_filters_schema_invalid_calls(
    tmp_path,
    stream,
):
    _app, client, _made = _app_client(tmp_path, INVALID_STRICT_READ_CALL)

    response = _post(client, {
        "input": "read README",
        "stream": stream,
        "tools": [{**READ_TOOL, "strict": True}],
    })

    assert response.status_code == 200
    if stream:
        assert "response.function_call_arguments" not in response.text
    else:
        assert not any(
            item["type"] == "function_call"
            for item in response.json()["output"]
        )


@pytest.mark.parametrize(
    "extra_field",
    [
        {"allowed_callers": ["programmatic"]},
        {"defer_loading": True},
        {"output_schema": {"type": "object"}},
        {"future_semantic": True},
    ],
)
def test_responses_rejects_unimplemented_function_tool_semantics_before_upstream(
    tmp_path,
    extra_field,
):
    _app, client, made = _app_client(tmp_path, READ_CALL)

    response = _post(client, {
        "input": "read README",
        "tools": [{**READ_TOOL, **extra_field}],
    })

    assert response.status_code == 400
    assert "not supported" in response.text
    assert not made or made[-1].calls == []


def test_responses_canonicalizes_tool_choice_in_response(tmp_path):
    _app, client, _made = _app_client(tmp_path, "plain answer")

    response = _post(client, {
        "input": "answer",
        "tools": [READ_TOOL],
        "tool_choice": " AUTO ",
    })

    assert response.status_code == 200
    assert response.json()["tool_choice"] == "auto"


def test_responses_function_call_output_becomes_continuation_turn():
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": [
            {
                "type": "function_call",
                "call_id": "call_123",
                "name": "Read",
                "arguments": '{"file_path":"S:/repo/README.md"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_123",
                "output": "line from the real file",
            },
        ],
        "tools": [READ_TOOL],
    })

    translated = translate_responses_request(request)
    transcript = _context(translated, "Prior conversation transcript:\n")

    assert translated.prompt.startswith("The tool action you requested has been executed")
    assert "Assistant called tool (id: call_123): Read" in transcript
    assert "Tool: Tool result (id: call_123)" in transcript
    assert "line from the real file" in transcript


def test_m365_previous_response_id_resumes_explicit_header_session(tmp_path):
    _app, client, _made = _app_client(tmp_path, READ_CALL)
    headers = {
        "Authorization": "Bearer k",
        "x-m365-session-id": "responses-explicit-session",
    }

    first = client.post(
        "/v1/responses",
        headers=headers,
        json={
            "model": "m365-copilot",
            "input": "read README",
            "tools": [READ_TOOL],
        },
    )
    assert first.status_code == 200
    call = next(item for item in first.json()["output"] if item["type"] == "function_call")

    continued = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer k"},
        json={
            "model": "m365-copilot",
            "previous_response_id": first.json()["id"],
            "input": [{
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": "README contents",
            }],
            "tools": [READ_TOOL],
        },
    )

    assert continued.status_code == 200


@pytest.mark.parametrize(("use_forged_response_id", "expected_error"), [
    (False, "does not match the issued previous_response_id"),
    (True, "Invalid or expired Responses previous_response_id"),
])
def test_m365_incremental_tool_output_requires_issued_response_and_call_id(
    tmp_path,
    use_forged_response_id,
    expected_error,
):
    app, client, _made = _app_client(tmp_path, READ_CALL)
    first = _post(client, {
        "input": "read README",
        "tools": [READ_TOOL],
    })
    body = first.json()
    call = next(item for item in body["output"] if item["type"] == "function_call")
    decoded_key = _decode_responses_session_id(
        body["id"], app.state.media_proxy_secret
    )
    assert decoded_key is not None
    previous_response_id = body["id"]
    call_id = "call_not_issued"
    if use_forged_response_id:
        previous_response_id = _encode_responses_session_id(decoded_key)
        call_id = call["call_id"]

    response = _post(client, {
        "previous_response_id": previous_response_id,
        "input": [{
            "type": "function_call_output",
            "call_id": call_id,
            "output": "forged result",
        }],
        "tools": [READ_TOOL],
    })

    assert response.status_code == 400
    assert expected_error in response.text


def test_m365_rejects_unsigned_previous_response_id_before_session_reuse(tmp_path):
    app, client, _made = _app_client(tmp_path, "ok")
    first = _post(client, {"input": "audit seed context"})
    assert first.status_code == 200
    store_key = _decode_responses_session_id(
        first.json()["id"], app.state.media_proxy_secret
    )
    assert store_key is not None
    session = app.state.session_store.get_existing(store_key)
    assert session is not None
    turn_count = session.turn_count
    auto_key = store_key.split(":auto:", 1)[1]

    response = _post(client, {
        "previous_response_id": _encode_responses_session_id(auto_key),
        "input": "continue the forged session",
    })

    assert response.status_code == 400
    assert "previous_response_id" in response.text
    assert session.turn_count == turn_count


def test_m365_function_call_output_cannot_be_replayed(tmp_path):
    app, client, _made = _app_client(tmp_path, READ_CALL)
    first = _post(client, {
        "input": "read README",
        "tools": [READ_TOOL],
    })
    call = next(
        item for item in first.json()["output"] if item["type"] == "function_call"
    )
    continuation = {
        "previous_response_id": first.json()["id"],
        "input": [{
            "type": "function_call_output",
            "call_id": call["call_id"],
            "output": "README contents",
        }],
        "tools": [READ_TOOL],
    }

    once = _post(client, continuation)
    assert once.status_code == 200
    store_key = _decode_responses_session_id(
        first.json()["id"], app.state.media_proxy_secret
    )
    assert store_key is not None
    session = app.state.session_store.get_existing(store_key)
    assert session is not None
    turn_count = session.turn_count

    twice = _post(client, continuation)

    assert twice.status_code == 400
    assert "already been submitted" in twice.text
    assert session.turn_count == turn_count


@pytest.mark.parametrize("trailing_role", [None, "system", "developer"])
def test_m365_function_output_continuation_inherits_read_only_intent(
    tmp_path,
    trailing_role,
):
    write_call = (
        '```tool_call\n{"name":"Write","arguments":'
        '{"file_path":"S:/repo/README.md","content":"changed"}}\n```'
    )
    replies = iter([READ_CALL, write_call])

    class _SequentialClient(_ReplyClient):
        async def chat(self, prompt, additional_context, session=None, images=None):
            self.calls.append((prompt, additional_context))
            if session is not None:
                session.reserve_turn()
            return next(replies)

    shared_client = _SequentialClient("")
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **_kwargs: shared_client,
    )
    client = TestClient(app)
    first = _post(client, {
        "input": "Read README only; do not modify or write anything.",
        "tools": [READ_TOOL, WRITE_TOOL],
    })
    call = next(
        item for item in first.json()["output"] if item["type"] == "function_call"
    )

    continuation_input = [{
        "type": "function_call_output",
        "call_id": call["call_id"],
        "output": "README contents",
    }]
    if trailing_role is not None:
        continuation_input.append({
            "role": trailing_role,
            "content": "Continue following the existing task constraints.",
        })
    continued = _post(client, {
        "previous_response_id": first.json()["id"],
        "input": continuation_input,
        "tools": [READ_TOOL, WRITE_TOOL],
    })

    assert continued.status_code == 200
    assert not [
        item for item in continued.json()["output"]
        if item["type"] == "function_call"
    ]
    assert [entry["read_only_guard"] for entry in app.state.call_log[-2:]] == [
        True,
        True,
    ]


def test_responses_latest_user_turn_replaces_old_read_only_intent(tmp_path):
    write_call = (
        '```tool_call\n{"name":"Write","arguments":'
        '{"file_path":"x.txt","content":"ok"}}\n```'
    )
    app, client, _made = _app_client(tmp_path, write_call)

    response = _post(client, {
        "input": [
            {"role": "user", "content": "Read only; do not write."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "Now write x.txt."},
        ],
        "tools": [WRITE_TOOL],
    })

    assert response.status_code == 200
    assert any(
        item["type"] == "function_call" and item["name"] == "Write"
        for item in response.json()["output"]
    )
    assert app.state.call_log[-1]["read_only_guard"] is False


def test_m365_text_continuation_does_not_inherit_read_only_intent(tmp_path):
    write_call = (
        '```tool_call\n{"name":"Write","arguments":'
        '{"file_path":"x.txt","content":"ok"}}\n```'
    )
    app, client, _made = _app_client(tmp_path, write_call)
    first = _post(client, {
        "input": "Read only; do not write.",
        "tools": [WRITE_TOOL],
    })

    continued = _post(client, {
        "previous_response_id": first.json()["id"],
        "input": "Now write x.txt.",
        "tools": [WRITE_TOOL],
    })

    assert continued.status_code == 200
    assert any(
        item["type"] == "function_call" and item["name"] == "Write"
        for item in continued.json()["output"]
    )
    assert app.state.call_log[-1]["read_only_guard"] is False


def test_m365_invalid_continuation_does_not_consume_previous_response_id(tmp_path):
    _app, client, _made = _app_client(tmp_path, READ_CALL)
    first = _post(client, {
        "input": "read README",
        "tools": [READ_TOOL],
    })
    call = next(
        item for item in first.json()["output"] if item["type"] == "function_call"
    )
    previous_response_id = first.json()["id"]

    invalid = _post(client, {
        "previous_response_id": previous_response_id,
        "input": [{
            "type": "function_call_output",
            "call_id": call["call_id"],
            "output": [{"type": "input_image", "image_url": "https://example.test/x"}],
        }],
        "tools": [READ_TOOL],
    })
    corrected = _post(client, {
        "previous_response_id": previous_response_id,
        "input": [{
            "type": "function_call_output",
            "call_id": call["call_id"],
            "output": "README contents",
        }],
        "tools": [READ_TOOL],
    })

    assert invalid.status_code == 400
    assert corrected.status_code == 200


def test_m365_local_validation_failure_releases_previous_response_id(tmp_path):
    app, client, _made = _app_client(tmp_path, "ok")
    app.state.run_permission = "read_only"
    first = _post(client, {"input": "seed response"})
    previous_response_id = first.json()["id"]

    rejected = _post(client, {
        "previous_response_id": previous_response_id,
        "input": "write a file",
        "tools": [WRITE_TOOL],
        "tool_choice": "required",
    })
    corrected = _post(client, {
        "previous_response_id": previous_response_id,
        "input": "continue without a tool",
    })

    assert rejected.status_code == 400
    assert corrected.status_code == 200


def test_m365_required_tool_502_releases_previous_response_id(tmp_path):
    _app, client, _made = _app_client(tmp_path, "plain prose")
    first = _post(client, {"input": "seed response"})
    previous_response_id = first.json()["id"]

    failed = _post(client, {
        "previous_response_id": previous_response_id,
        "input": "read README",
        "tools": [READ_TOOL],
        "tool_choice": "required",
    })
    corrected = _post(client, {
        "previous_response_id": previous_response_id,
        "input": "continue without a tool",
    })

    assert failed.status_code == 502
    assert corrected.status_code == 200


def test_m365_unexpected_nonstream_failure_releases_previous_response_id(tmp_path):
    clients = iter([
        _ReplyClient("seed response"),
        _RuntimeFailingClient("unexpected failure"),
        _ReplyClient("recovered response"),
    ])

    def factory(**_kwargs):
        return next(clients)

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=factory,
    )
    client = TestClient(app, raise_server_exceptions=False)
    first = _post(client, {"input": "seed response"})
    previous_response_id = first.json()["id"]

    failed = _post(client, {
        "previous_response_id": previous_response_id,
        "input": "continue once",
    })
    retried = _post(client, {
        "previous_response_id": previous_response_id,
        "input": "retry after the server failure",
    })

    assert failed.status_code == 500
    assert retried.status_code == 200


def test_m365_parallel_tool_outputs_must_be_submitted_together(tmp_path):
    _app, client, _made = _app_client(tmp_path, PARALLEL_READ_CALLS)
    first = _post(client, {
        "input": "read both files",
        "tools": [READ_TOOL],
    })
    calls = [
        item for item in first.json()["output"]
        if item["type"] == "function_call"
    ]
    assert len(calls) == 2
    previous_response_id = first.json()["id"]

    text_only = _post(client, {
        "previous_response_id": previous_response_id,
        "input": "continue without the outstanding tool results",
        "tools": [READ_TOOL],
    })
    partial = _post(client, {
        "previous_response_id": previous_response_id,
        "input": [{
            "type": "function_call_output",
            "call_id": calls[0]["call_id"],
            "output": "A",
        }],
        "tools": [READ_TOOL],
    })
    complete = _post(client, {
        "previous_response_id": previous_response_id,
        "input": [
            {
                "type": "function_call_output",
                "call_id": calls[1]["call_id"],
                "output": "B",
            },
            {
                "type": "function_call_output",
                "call_id": calls[0]["call_id"],
                "output": "A",
            },
        ],
        "tools": [READ_TOOL],
    })

    assert text_only.status_code == 400
    assert partial.status_code == 400
    assert complete.status_code == 200


def test_session_store_ignores_malformed_response_tracking_fields(tmp_path):
    persist_path = tmp_path / "sessions.json"
    persist_path.write_text(json.dumps({
        "tenant:session": {
            "conversation_id": "conversation",
            "client_session_id": "client",
            "turn_count": 2,
            "issued_response_calls": ["not", "a", "mapping"],
            "issued_response_read_only": ["not", "a", "mapping"],
            "consumed_response_ids": "not-a-list",
        },
    }), encoding="utf-8")

    store = PersistentSessionStore(persist_path=persist_path)
    session = store.get_existing("tenant:session")

    assert session is not None
    assert session.issued_response_calls == {}
    assert session.issued_response_read_only == {}
    assert session.consumed_response_ids == []


def test_session_store_filters_read_only_state_for_malformed_call_entries(tmp_path):
    persist_path = tmp_path / "sessions.json"
    persist_path.write_text(json.dumps({
        "tenant:session": {
            "conversation_id": "conversation",
            "client_session_id": "client",
            "issued_response_calls": {
                "resp_valid": [],
                "resp_invalid": "not-a-list",
            },
            "issued_response_read_only": {
                "resp_valid": True,
                "resp_invalid": True,
            },
        },
    }), encoding="utf-8")

    session = PersistentSessionStore(
        persist_path=persist_path
    ).get_existing("tenant:session")

    assert session is not None
    assert session.issued_response_calls == {"resp_valid": []}
    assert session.issued_response_read_only == {"resp_valid": True}


def test_session_store_persists_response_read_only_state(tmp_path):
    persist_path = tmp_path / "sessions.json"
    store = PersistentSessionStore(persist_path=persist_path)
    session = store.get("tenant:session")
    session.record_response("resp_read_only", ["call_1"], read_only=True)

    restored = PersistentSessionStore(persist_path=persist_path).get_existing(
        "tenant:session"
    )

    assert restored is not None
    assert restored.response_is_read_only("resp_read_only")


def test_session_store_persists_encrypted_router_continuation_context(tmp_path):
    persist_path = tmp_path / "sessions.json"
    key_path = tmp_path / ".enc_key"
    store = PersistentSessionStore(
        persist_path=persist_path,
        encryption_key_path=key_path,
    )
    session = store.get("tenant:session")
    context = {
        "prompt": "original-task-sentinel",
        "additional_context": ["System instructions:\nkeep constraints"],
    }

    session.record_response(
        "resp_router",
        ["call_1"],
        response_context=context,
    )

    assert "original-task-sentinel" not in persist_path.read_text(encoding="utf-8")
    restored = PersistentSessionStore(
        persist_path=persist_path,
        encryption_key_path=key_path,
    ).get_existing("tenant:session")
    assert restored is not None
    assert restored.response_context("resp_router") == context


def test_session_store_persists_encrypted_text_continuation_context(tmp_path):
    persist_path = tmp_path / "sessions.json"
    key_path = tmp_path / ".enc_key"
    store = PersistentSessionStore(
        persist_path=persist_path,
        encryption_key_path=key_path,
    )
    context = {
        "prompt": "studio-text-task-sentinel",
        "additional_context": [],
    }

    store.get("tenant:session").record_response(
        "resp_text",
        [],
        response_context=context,
    )

    assert "studio-text-task-sentinel" not in persist_path.read_text(
        encoding="utf-8"
    )
    restored = PersistentSessionStore(
        persist_path=persist_path,
        encryption_key_path=key_path,
    ).get_existing("tenant:session")
    assert restored is not None
    assert restored.response_context("resp_text") == context


def test_session_context_moves_to_child_call_and_clears_on_completion():
    session = PersistentSession()
    parent_context = {"prompt": "first", "additional_context": []}
    child_context = {"prompt": "continue", "additional_context": ["first"]}
    session.record_response(
        "resp_parent",
        ["call_parent"],
        response_context=parent_context,
    )
    parent_reservation = session.begin_response_continuation("resp_parent")
    assert parent_reservation

    assert session.complete_response_continuation(
        "resp_parent",
        parent_reservation,
        "resp_child",
        ["call_child"],
        child_response_context=child_context,
    )
    assert session.response_context("resp_parent") is None
    assert session.response_context("resp_child") == child_context

    child_reservation = session.begin_response_continuation("resp_child")
    assert child_reservation
    assert session.complete_response_continuation(
        "resp_child",
        child_reservation,
        "resp_done",
        [],
    )
    assert session.response_context("resp_child") is None
    assert session.response_context("resp_done") is None


def test_session_store_migrates_latest_response_head(tmp_path):
    persist_path = tmp_path / "sessions.json"
    persist_path.write_text(json.dumps({
        "tenant:session": {
            "conversation_id": "conversation",
            "client_session_id": "client",
            "issued_response_calls": {
                "resp_old": [],
                "resp_latest": ["call_1"],
            },
            "latest_response_id": "resp_missing",
        },
    }), encoding="utf-8")

    store = PersistentSessionStore(persist_path=persist_path)
    session = store.get_existing("tenant:session")

    assert session is not None
    assert session.latest_response_id == "resp_latest"
    assert session.begin_response_continuation("resp_latest")


def test_session_store_ignores_non_utf8_persistence_file(tmp_path):
    persist_path = tmp_path / "sessions.json"
    persist_path.write_bytes(b"\xff\xfe\x00")

    store = PersistentSessionStore(persist_path=persist_path)

    assert store.get_existing("missing") is None


def test_responses_stream_cleanup_releases_cancelled_continuation():
    session = PersistentSession()
    response_id = "resp_cancelled"
    session.record_response(response_id, [])
    reservation = session.begin_response_continuation(response_id)
    assert reservation

    async def source():
        yield "first event"
        yield "second event"

    async def disconnect_after_one_event():
        await session.response_lock.acquire()
        response = routes_api_responses._ResponsesStreamingResponse(
            source(),
            on_request_done=lambda success: session.finish_response_continuation(
                response_id, reservation, success
            ),
            response_lock=session.response_lock,
        )

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("client disconnected")

        with pytest.raises(ClientDisconnect):
            await response(
                {"type": "http", "asgi": {"spec_version": "2.4"}},
                receive,
                send,
            )

    asyncio.run(disconnect_after_one_event())

    assert not session.response_lock.locked()
    assert session.begin_response_continuation(response_id)


def test_responses_streaming_response_closes_body_on_early_disconnect():
    session = PersistentSession()
    response_id = "resp_disconnect"
    session.record_response(response_id, [])
    reservation = session.begin_response_continuation(response_id)
    assert reservation

    async def source():
        yield "event"

    async def disconnect_before_body_iteration():
        await session.response_lock.acquire()
        response = routes_api_responses._ResponsesStreamingResponse(
            source(),
            on_request_done=lambda success: session.finish_response_continuation(
                response_id, reservation, success
            ),
            response_lock=session.response_lock,
        )

        async def receive():
            return {"type": "http.disconnect"}

        async def send(_message):
            await asyncio.sleep(1)

        await response(
            {"type": "http", "asgi": {"spec_version": "2.0"}},
            receive,
            send,
        )

    asyncio.run(disconnect_before_body_iteration())

    assert not session.response_lock.locked()
    assert session.begin_response_continuation(response_id)


def test_responses_continuation_cleanup_cannot_clear_a_new_reservation():
    session = PersistentSession()
    response_id = "resp_retry"
    session.record_response(response_id, [])
    first_reservation = session.begin_response_continuation(response_id)
    assert first_reservation

    session.finish_response_continuation(response_id, first_reservation, False)
    second_reservation = session.begin_response_continuation(response_id)
    assert second_reservation

    session.finish_response_continuation(response_id, first_reservation, False)

    assert not session.begin_response_continuation(response_id)
    session.finish_response_continuation(response_id, second_reservation, False)
    assert session.begin_response_continuation(response_id)


def test_responses_stream_finalizes_before_completed_event_is_yielded():
    statuses: list[bool] = []

    async def read_until_completed():
        stream = response_helpers._responses_stream(
            "m365-copilot",
            _ReplyClient("hello"),
            "hi",
            [],
            on_request_done=statuses.append,
        )
        async for event in stream:
            if "event: response.completed" in event:
                assert statuses == [True]
                break
        await stream.aclose()

    asyncio.run(read_until_completed())


def test_responses_tool_stream_finalizes_before_completed_event_is_yielded():
    statuses: list[bool] = []

    async def read_until_completed():
        stream = response_helpers._responses_stream_with_tools(
            "m365-copilot",
            _ReplyClient(READ_CALL),
            "read README",
            [],
            tool_names={"Read"},
            on_request_done=statuses.append,
        )
        async for event in stream:
            if "event: response.completed" in event:
                assert statuses == [True]
                break
        await stream.aclose()

    asyncio.run(read_until_completed())


def test_responses_stream_finalizes_before_failed_event_is_yielded():
    statuses: list[bool] = []

    async def read_until_failed():
        stream = response_helpers._responses_stream(
            "m365-copilot",
            _FailingStreamClient("upstream broke"),
            "hi",
            [],
            on_request_done=statuses.append,
        )
        async for event in stream:
            if "event: response.failed" in event:
                assert statuses == [False]
                break
        await stream.aclose()

    asyncio.run(read_until_failed())


def test_m365_text_stream_response_id_can_continue_once(tmp_path):
    _app, client, _made = _app_client(tmp_path, "hello")
    first = _post(client, {
        "input": "first turn",
        "stream": True,
    })
    completed = next(
        event["response"]
        for event in _events(first)
        if event["type"] == "response.completed"
    )
    continuation = {
        "previous_response_id": completed["id"],
        "input": "second turn",
    }

    once = _post(client, continuation)
    twice = _post(client, continuation)

    assert once.status_code == 200
    assert twice.status_code == 400
    assert "already" in twice.text


def test_m365_previous_response_id_must_be_latest_session_head(tmp_path):
    _app, client, _made = _app_client(tmp_path, "ok")
    headers = {
        "Authorization": "Bearer k",
        "x-m365-session-id": "responses-linear-head",
    }
    first = client.post(
        "/v1/responses",
        headers=headers,
        json={"model": "m365-copilot", "input": "first"},
    )
    second = client.post(
        "/v1/responses",
        headers=headers,
        json={"model": "m365-copilot", "input": "second"},
    )

    stale = _post(client, {
        "previous_response_id": first.json()["id"],
        "input": "must not attach after second",
    })
    latest = _post(client, {
        "previous_response_id": second.json()["id"],
        "input": "continue latest",
    })

    assert stale.status_code == 400
    assert "latest response" in stale.text
    assert latest.status_code == 200


def test_session_atomically_records_child_and_consumes_parent():
    session = PersistentSession()
    session.record_response("resp_parent", ["call_a"])
    reservation = session.begin_response_continuation("resp_parent")
    assert reservation
    saves: list[int] = []
    session._on_change = lambda: saves.append(1)

    completed = session.complete_response_continuation(
        "resp_parent",
        reservation,
        "resp_child",
        [],
    )

    assert completed
    assert saves == [1]
    assert session.latest_response_id == "resp_child"
    assert "resp_parent" in session.consumed_response_ids
    assert session.issued_response_calls["resp_child"] == []


def test_m365_required_retry_is_atomic_against_same_session_requests(tmp_path):
    order: list[str] = []
    first_turn_started = asyncio.Event()

    class _CoordinatedClient(_ReplyClient):
        async def chat(self, prompt, additional_context, session=None, images=None):
            if session is not None:
                session.reserve_turn()
            if prompt == "request A":
                order.append("A-first")
                first_turn_started.set()
                await asyncio.sleep(0.05)
                return "plain prose"
            if prompt.startswith("Your previous response did not satisfy"):
                order.append("A-retry")
                return READ_CALL
            order.append("B")
            return "B done"

    shared_client = _CoordinatedClient("")
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **_kwargs: shared_client,
    )

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            headers = {
                "Authorization": "Bearer k",
                "x-m365-session-id": "atomic-required-retry",
            }
            request_a = asyncio.create_task(client.post(
                "/v1/responses",
                headers=headers,
                json={
                    "model": "m365-copilot",
                    "input": "request A",
                    "tools": [READ_TOOL],
                    "tool_choice": "required",
                },
            ))
            await first_turn_started.wait()
            request_b = asyncio.create_task(client.post(
                "/v1/responses",
                headers=headers,
                json={"model": "m365-copilot", "input": "request B"},
            ))
            return await request_a, await request_b

    response_a, response_b = asyncio.run(exercise())

    assert response_a.status_code == response_b.status_code == 200
    assert order == ["A-first", "A-retry", "B"]


def test_m365_streaming_required_retry_is_atomic_against_same_session_requests(
    tmp_path,
):
    order: list[str] = []
    first_turn_started = asyncio.Event()

    class _CoordinatedStreamClient(_ReplyClient):
        async def chat_stream(
            self, prompt, additional_context, session=None, images=None
        ):
            if session is not None:
                session.reserve_turn()
            if prompt == "request A":
                order.append("A-first")
                first_turn_started.set()
                await asyncio.sleep(0.05)
                yield "plain prose"
                return
            if prompt.startswith("Your previous response did not satisfy"):
                order.append("A-retry")
                yield READ_CALL
                return
            raise AssertionError(f"unexpected streaming prompt: {prompt}")

        async def chat(self, prompt, additional_context, session=None, images=None):
            if session is not None:
                session.reserve_turn()
            order.append("B")
            return "B done"

    shared_client = _CoordinatedStreamClient("")
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **_kwargs: shared_client,
    )

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            headers = {
                "Authorization": "Bearer k",
                "x-m365-session-id": "atomic-streaming-required-retry",
            }
            request_a = asyncio.create_task(client.post(
                "/v1/responses",
                headers=headers,
                json={
                    "model": "m365-copilot",
                    "input": "request A",
                    "stream": True,
                    "tools": [READ_TOOL],
                    "tool_choice": "required",
                },
            ))
            await first_turn_started.wait()
            request_b = asyncio.create_task(client.post(
                "/v1/responses",
                headers=headers,
                json={"model": "m365-copilot", "input": "request B"},
            ))
            return await request_a, await request_b

    response_a, response_b = asyncio.run(exercise())

    assert response_a.status_code == response_b.status_code == 200
    assert "event: response.completed" in response_a.text
    assert order == ["A-first", "A-retry", "B"]


def test_m365_same_input_without_previous_response_id_starts_new_session(tmp_path):
    app, client, _made = _app_client(tmp_path, "ok")

    first = _post(client, {"input": "same standalone request"})
    second = _post(client, {"input": "same standalone request"})

    assert first.status_code == second.status_code == 200
    first_key = _decode_responses_session_id(
        first.json()["id"], app.state.media_proxy_secret
    )
    second_key = _decode_responses_session_id(
        second.json()["id"], app.state.media_proxy_secret
    )
    assert first_key is not None and second_key is not None
    assert first_key != second_key
    assert app.state.session_store.get_existing(first_key) is not (
        app.state.session_store.get_existing(second_key)
    )


def test_m365_invalid_responses_input_does_not_create_session(tmp_path):
    app, client, made = _app_client(tmp_path, "unused")
    sessions_before = list(app.state.session_store._sessions)

    response = _post(client, {
        "input": [{"type": "unsupported"}],
    })

    assert response.status_code == 400
    assert "Unsupported Responses input item type" in response.text
    assert list(app.state.session_store._sessions) == sessions_before
    assert not made or made[-1].calls == []


def test_responses_preserves_call_ids_for_out_of_order_parallel_outputs():
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": [
            {
                "type": "function_call",
                "call_id": "call_a",
                "name": "Read",
                "arguments": '{"file_path":"a.txt"}',
            },
            {
                "type": "function_call",
                "call_id": "call_b",
                "name": "Read",
                "arguments": '{"file_path":"b.txt"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_b",
                "output": "B",
            },
            {
                "type": "function_call_output",
                "call_id": "call_a",
                "output": "A",
            },
        ],
        "tools": [READ_TOOL],
    })

    translated = translate_responses_request(request)
    transcript = _context(translated, "Prior conversation transcript:\n")

    assert "Assistant called tool (id: call_a): Read" in transcript
    assert "Assistant called tool (id: call_b): Read" in transcript
    assert "Tool: Tool result (id: call_b)\nB" in transcript
    assert "Tool: Tool result (id: call_a)\nA" in transcript


@pytest.mark.parametrize("item,error", [
    (
        {
            "type": "function_call",
            "name": "Read",
            "arguments": "{}",
        },
        "function_call items require a call_id",
    ),
    (
        {
            "type": "function_call",
            "call_id": "call_123",
            "name": "Read",
        },
        "function_call items require arguments as a JSON string",
    ),
    (
        {
            "type": "function_call",
            "call_id": "call_123",
            "name": "Read",
            "arguments": "not-json",
        },
        "function_call arguments must encode a JSON object",
    ),
])
def test_responses_rejects_incomplete_function_call_history(item, error):
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": [
            item,
            {"role": "user", "content": "continue"},
        ],
        "tools": [READ_TOOL],
    })

    with pytest.raises(ValueError, match=error):
        translate_responses_request(request)


@pytest.mark.parametrize("output,error", [
    (None, "function_call_output items require an output"),
    (
        [{"type": "input_image", "image_url": "https://example.test/a.png"}],
        "function_call_output output supports only text",
    ),
])
def test_responses_rejects_missing_or_unsupported_function_output(output, error):
    output_item = {
        "type": "function_call_output",
        "call_id": "call_123",
    }
    if output is not None:
        output_item["output"] = output
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": [
            {
                "type": "function_call",
                "call_id": "call_123",
                "name": "Read",
                "arguments": "{}",
            },
            output_item,
        ],
        "tools": [READ_TOOL],
    })

    with pytest.raises(ValueError, match=error):
        translate_responses_request(request)


def test_responses_rejects_unmatched_function_call_output_for_stateless_request():
    request = OpenAIResponsesRequest.model_validate({
        "model": "copilot-reasoning",
        "input": [{
            "type": "function_call_output",
            "call_id": "call_missing",
            "output": "real tool result",
        }],
        "previous_response_id": "resp_from_an_earlier_turn",
        "tools": [READ_TOOL],
    })

    with pytest.raises(ValueError, match="must resend the matching function_call"):
        translate_responses_request(request)


def test_responses_rejects_function_output_with_mismatched_call_id():
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": [
            {
                "type": "function_call",
                "call_id": "call_123",
                "name": "Read",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "call_other",
                "output": "real tool result",
            },
        ],
        "tools": [READ_TOOL],
    })

    with pytest.raises(ValueError, match="does not match a prior function_call"):
        translate_responses_request(request)


@pytest.mark.parametrize("items,error", [
    (
        [
            {
                "type": "function_call",
                "call_id": "call_123",
                "name": "Read",
                "arguments": "{}",
            },
            {
                "type": "function_call",
                "call_id": "call_123",
                "name": "Read",
                "arguments": "{}",
            },
            {"role": "user", "content": "continue"},
        ],
        "duplicate function_call call_id",
    ),
    (
        [
            {
                "type": "function_call",
                "call_id": "call_123",
                "name": "Read",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "call_123",
                "output": "first",
            },
            {
                "type": "function_call_output",
                "call_id": "call_123",
                "output": "second",
            },
        ],
        "duplicate function_call_output call_id",
    ),
])
def test_responses_rejects_duplicate_function_history_ids(items, error):
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": items,
        "tools": [READ_TOOL],
    })

    with pytest.raises(ValueError, match=error):
        translate_responses_request(request)


def test_responses_allows_incremental_m365_function_output_with_server_history():
    request = OpenAIResponsesRequest.model_validate({
        "model": "m365-copilot",
        "input": [{
            "type": "function_call_output",
            "call_id": "call_from_server_history",
            "output": "real tool result",
        }],
        "tools": [READ_TOOL],
    })

    translated = translate_responses_request(
        request,
        allow_unmatched_function_call_outputs=True,
    )

    assert "real tool result" in _context(
        translated, "Prior conversation transcript:\n"
    )


@pytest.mark.parametrize("tool_type", [
    "web_search",
    "web_search_2025_08_26",
    "file_search",
    "mcp",
    "code_interpreter",
    "custom",
    "shell",
    "local_shell",
    "computer_use_preview",
    "image_generation",
    "apply_patch",
])
def test_responses_rejects_hosted_tools_before_upstream_call(tmp_path, tool_type):
    _app, client, made = _app_client(tmp_path, "unused")

    response = _post(client, {
        "input": "use a hosted tool",
        "tools": [{"type": tool_type}],
    })

    assert response.status_code == 400
    assert "only function tools are supported" in response.text
    assert not made or made[-1].calls == []


def test_responses_non_stream_returns_message_and_function_call_items(tmp_path):
    app, client, _made = _app_client(tmp_path, READ_CALL)

    response = _post(client, {
        "input": "read README",
        "tools": [READ_TOOL],
    })

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert [item["type"] for item in body["output"]] == ["message", "function_call"]
    message, call = body["output"]
    assert message["status"] == "completed"
    assert "tool_call" not in message["content"][0]["text"]
    assert message["content"][0]["text"] == "I'll inspect it."
    assert message["content"][0]["annotations"] == []
    assert message["content"][0]["logprobs"] == []
    assert call["name"] == "Read"
    assert call["call_id"].startswith("call_")
    assert call["id"].startswith("fc_")
    assert call["status"] == "completed"
    assert json.loads(call["arguments"]) == {"file_path": "S:/repo/README.md"}
    assert body["parallel_tool_calls"] is True
    assert body["tool_choice"] == "auto"
    assert body["tools"][0]["name"] == "Read"
    assert body["usage"]["input_tokens"] > 0
    assert body["usage"]["output_tokens"] > 0
    assert body["usage"]["total_tokens"] == (
        body["usage"]["input_tokens"] + body["usage"]["output_tokens"]
    )
    assert body["usage"]["estimated"] is True
    assert app.state.call_log[-1]["tools"] == ["Read"]
    assert app.state.call_log[-1]["tool_calls_result"] == ["Read"]


def test_responses_non_stream_fake_file_retry_keeps_original_request_and_images(
    tmp_path,
):
    _app, client, made = _app_client(
        tmp_path,
        "file created",
        client_type=_ImageReplyClient,
    )
    marker = "Create S:/repo/unique-output.txt with marker RETRY_CONTEXT_42"

    response = _post(client, {
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": marker},
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,AA==",
                },
            ],
        }],
        "tools": [WRITE_TOOL],
    })

    assert response.status_code == 200
    upstream = made[-1]
    assert len(upstream.calls) == 2
    assert marker in upstream.calls[1][0]
    assert upstream.image_calls[0]
    assert upstream.image_calls[1] == upstream.image_calls[0]


def test_responses_tool_choice_none_disables_contract_and_parsing(tmp_path):
    app, client, made = _app_client(tmp_path, READ_CALL)

    response = _post(client, {
        "input": "answer without tools",
        "tools": [READ_TOOL],
        "tool_choice": "none",
    })

    assert response.status_code == 200
    assert [item["type"] for item in response.json()["output"]] == ["message"]
    prompt, context = made[-1].calls[-1]
    assert "tool_call" not in "\n".join(context)
    assert app.state.call_log[-1]["tools"] == []
    assert app.state.call_log[-1]["tool_choice"] == "none"


@pytest.mark.parametrize("reply", [INVALID_READ_CALL, NON_OBJECT_READ_CALL])
def test_responses_auto_discards_function_call_with_non_object_arguments(
    tmp_path, reply,
):
    app, client, made = _app_client(tmp_path, reply)

    response = _post(client, {
        "input": "read README",
        "tools": [READ_TOOL],
    })

    assert response.status_code == 200
    assert not [
        item for item in response.json()["output"]
        if item["type"] == "function_call"
    ]
    assert len(made[-1].calls) == 1
    assert app.state.call_log[-1]["tool_calls_result"] == []


@pytest.mark.parametrize("tool_choice", [
    "required",
    {"type": "function", "name": "Read"},
])
def test_responses_non_stream_fails_when_required_tool_is_not_returned(
    tmp_path, tool_choice,
):
    _app, client, made = _app_client(tmp_path, "plain prose")

    response = _post(client, {
        "input": "read README",
        "tools": [READ_TOOL],
        "tool_choice": tool_choice,
    })

    assert response.status_code == 502
    assert "required tool_choice" in response.text
    assert len(made[-1].calls) == 2


@pytest.mark.parametrize("tool_choice", [
    "required",
    {"type": "function", "name": "Read"},
])
def test_responses_non_stream_retries_malformed_required_tool_call(
    tmp_path, tool_choice,
):
    _app, client, made = _app_client(tmp_path, INVALID_READ_CALL)

    response = _post(client, {
        "input": "read README",
        "tools": [READ_TOOL],
        "tool_choice": tool_choice,
    })

    assert response.status_code == 502
    assert "required tool_choice" in response.text
    assert len(made[-1].calls) == 2


def test_responses_stream_fails_when_required_tool_is_not_returned(tmp_path):
    _app, client, made = _app_client(tmp_path, "plain prose")

    response = _post(client, {
        "input": "read README",
        "stream": True,
        "tools": [READ_TOOL],
        "tool_choice": "required",
    })

    assert response.status_code == 200
    events = _events(response)
    assert [event["type"] for event in events] == [
        "response.created",
        "response.in_progress",
        "error",
        "response.failed",
    ]
    assert events[2]["code"] == "server_error"
    assert "required tool_choice" in events[2]["message"]
    assert events[3]["response"]["status"] == "failed"
    assert len(made[-1].calls) == 2


def test_responses_stream_retries_malformed_required_tool_call(tmp_path):
    _app, client, made = _app_client(tmp_path, INVALID_READ_CALL)

    response = _post(client, {
        "input": "read README",
        "stream": True,
        "tools": [READ_TOOL],
        "tool_choice": "required",
    })

    assert response.status_code == 200
    events = _events(response)
    assert [event["type"] for event in events] == [
        "response.created",
        "response.in_progress",
        "error",
        "response.failed",
    ]
    assert "required tool_choice" in events[2]["message"]
    assert events[3]["response"]["status"] == "failed"
    assert len(made[-1].calls) == 2


def test_responses_required_stream_logs_retry_failure(tmp_path):
    app, client, _made = _app_client(
        tmp_path,
        "upstream broke",
        client_type=_RetryFailingStreamClient,
    )

    response = _post(client, {
        "input": "read README",
        "stream": True,
        "tools": [READ_TOOL],
        "tool_choice": "required",
    })

    assert response.status_code == 200
    assert app.state.call_log[-1]["retried"] is True
    assert app.state.call_log[-1]["error"] == "upstream broke"
    assert app.state.call_log[-1]["tool_calls_result"] == []


def test_responses_text_stream_upstream_failure_is_logged(tmp_path):
    app, client, _made = _app_client(
        tmp_path,
        "upstream broke",
        _FailingStreamClient,
    )

    response = _post(client, {
        "input": "hello",
        "stream": True,
    })

    assert response.status_code == 200
    assert app.state.call_log[-1]["error"] == "upstream broke"
    assert app.state.call_log[-1]["response_text"] == ""
    assert app.state.call_log[-1]["tool_calls_result"] == []


def test_responses_non_stream_upstream_failure_is_logged(tmp_path):
    app, client, _made = _app_client(
        tmp_path,
        "upstream broke",
        client_type=_FailingClient,
    )

    response = _post(client, {"input": "hello"})

    assert response.status_code == 502
    assert app.state.call_log[-1]["error"] == "upstream broke"
    assert app.state.call_log[-1]["tool_calls_result"] == []


def test_responses_filters_calls_for_undeclared_tools(tmp_path):
    reply = (
        '```tool_call\n{"name":"Read","arguments":{"file_path":"a"}}\n```\n'
        '```tool_call\n{"name":"Write","arguments":{"file_path":"b","content":"x"}}\n```'
    )
    _app, client, _made = _app_client(tmp_path, reply)

    response = _post(client, {
        "input": "inspect only",
        "tools": [READ_TOOL],
    })

    calls = [item for item in response.json()["output"] if item["type"] == "function_call"]
    assert [call["name"] for call in calls] == ["Read"]


def test_responses_does_not_leak_an_undeclared_tool_block_as_text(tmp_path):
    reply = (
        '```tool_call\n{"name":"Write","arguments":'
        '{"file_path":"b","content":"x"}}\n```'
    )
    _app, client, _made = _app_client(tmp_path, reply)

    response = _post(client, {
        "input": "inspect only",
        "tools": [READ_TOOL],
    })

    assert response.status_code == 200
    assert [item["type"] for item in response.json()["output"]] == ["message"]
    assert response.json()["output"][0]["content"][0]["text"] == ""


def test_responses_parallel_false_keeps_only_first_declared_call(tmp_path):
    reply = (
        '```tool_call\n{"name":"Read","arguments":{"file_path":"a"}}\n```\n'
        '```tool_call\n{"name":"Write","arguments":{"file_path":"b","content":"x"}}\n```'
    )
    _app, client, _made = _app_client(tmp_path, reply)

    response = _post(client, {
        "input": "perform both actions",
        "tools": [READ_TOOL, WRITE_TOOL],
        "parallel_tool_calls": False,
    })

    calls = [item for item in response.json()["output"] if item["type"] == "function_call"]
    assert [call["name"] for call in calls] == ["Read"]


def test_responses_read_only_permission_filters_mutating_call(tmp_path):
    write_reply = (
        '```tool_call\n{"name":"Write","arguments":'
        '{"file_path":"S:/x.txt","content":"x"}}\n```'
    )
    app, client, _made = _app_client(tmp_path, write_reply)
    app.state.run_permission = "read_only"

    response = _post(client, {
        "input": "write a file",
        "tools": [WRITE_TOOL],
    })

    assert response.status_code == 200
    assert not [item for item in response.json()["output"] if item["type"] == "function_call"]
    assert "tool_call" not in response.json()["output"][0]["content"][0]["text"]
    assert app.state.call_log[-1]["read_only_guard"] is True
    assert app.state.call_log[-1]["tool_calls_result"] == []


@pytest.mark.parametrize("tool_choice", [
    "required",
    {"type": "function", "name": "Write"},
])
def test_responses_read_only_rejects_forced_mutating_tool_before_upstream(
    tmp_path,
    tool_choice,
):
    app, client, made = _app_client(tmp_path, "unused")
    app.state.run_permission = "read_only"
    sessions_before = list(app.state.session_store._sessions)

    response = _post(client, {
        "input": "write a file",
        "tools": [WRITE_TOOL],
        "tool_choice": tool_choice,
    })

    assert response.status_code == 400
    assert "read-only" in response.text.lower()
    assert list(app.state.session_store._sessions) == sessions_before
    assert not made or made[-1].calls == []


def test_responses_stream_emits_function_call_lifecycle(tmp_path):
    tool_only = (
        '```tool_call\n{"name":"Read","arguments":'
        '{"file_path":"S:/repo/README.md"}}\n```'
    )
    _app, client, _made = _app_client(tmp_path, tool_only)

    response = _post(client, {
        "input": "read README",
        "stream": True,
        "tools": [READ_TOOL],
    })

    assert response.status_code == 200
    assert "[DONE]" not in response.text
    events = _events(response)
    types = [event["type"] for event in events]
    assert _event_names(response) == types
    assert types == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert [event["sequence_number"] for event in events] == list(range(len(events)))

    added = events[2]
    assert added["item"]["type"] == "function_call"
    assert added["item"]["status"] == "in_progress"
    assert added["item"]["name"] == "Read"
    assert added["item"]["arguments"] == ""
    assert added["item"]["id"].startswith("fc_")
    assert added["item"]["call_id"].startswith("call_")

    arguments_delta = events[3]
    assert arguments_delta["item_id"] == added["item"]["id"]
    assert arguments_delta["output_index"] == 0
    assert json.loads(arguments_delta["delta"]) == {
        "file_path": "S:/repo/README.md",
    }

    arguments_done = events[4]
    assert arguments_done["item_id"] == added["item"]["id"]
    assert arguments_done["output_index"] == 0
    assert arguments_done["name"] == "Read"
    assert json.loads(arguments_done["arguments"]) == {
        "file_path": "S:/repo/README.md",
    }

    item_done = events[5]
    assert item_done["item"]["status"] == "completed"
    assert item_done["item"]["id"] == added["item"]["id"]
    assert item_done["item"]["call_id"] == added["item"]["call_id"]
    completed = events[-1]["response"]
    assert completed["status"] == "completed"
    assert completed["output"] == [item_done["item"]]
    assert json.loads(completed["output"][0]["arguments"]) == {
        "file_path": "S:/repo/README.md",
    }


def test_responses_tool_stream_dedupes_full_upstream_reemission(tmp_path):
    _app, client, _made = _app_client(
        tmp_path,
        READ_CALL,
        client_type=_RepeatedReplyStreamClient,
    )

    response = _post(client, {
        "input": "read README",
        "stream": True,
        "tools": [READ_TOOL],
    })

    events = _events(response)
    completed = events[-1]["response"]
    calls = [item for item in completed["output"] if item["type"] == "function_call"]
    assert len(calls) == 1
    assert calls[0]["name"] == "Read"


def test_responses_text_stream_emits_complete_item_lifecycle(tmp_path):
    _app, client, _made = _app_client(tmp_path, "hello")

    response = _post(client, {"input": "hi", "stream": True})

    events = _events(response)
    types = [event["type"] for event in events]
    assert types == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert [event["sequence_number"] for event in events] == list(range(len(events)))
    assert "[DONE]" not in response.text

    created, in_progress, item_added, part_added, delta, text_done, part_done, item_done, completed = events
    assert created["response"]["status"] == "in_progress"
    assert created["response"]["output"] == []
    assert created["response"]["parallel_tool_calls"] is True
    assert created["response"]["tool_choice"] == "auto"
    assert created["response"]["tools"] == []
    assert in_progress["response"]["status"] == "in_progress"

    item_id = item_added["item"]["id"]
    assert item_added["item"] == {
        "id": item_id,
        "type": "message",
        "status": "in_progress",
        "role": "assistant",
        "content": [],
    }
    assert part_added["item_id"] == item_id
    assert part_added["part"] == {
        "type": "output_text",
        "text": "",
        "annotations": [],
        "logprobs": [],
    }
    assert delta["item_id"] == item_id
    assert delta["delta"] == "hello"
    assert delta["logprobs"] == []
    assert text_done["item_id"] == item_id
    assert text_done["text"] == "hello"
    assert text_done["logprobs"] == []
    assert part_done["part"] == {
        "type": "output_text",
        "text": "hello",
        "annotations": [],
        "logprobs": [],
    }
    assert item_done["item"]["status"] == "completed"
    assert item_done["item"]["content"] == [part_done["part"]]
    assert completed["response"]["status"] == "completed"
    assert completed["response"]["output"] == [item_done["item"]]


def test_responses_stream_preserves_text_and_multiple_function_calls(tmp_path):
    reply = (
        "I'll perform both.\n\n"
        '```tool_call\n{"name":"Read","arguments":{"file_path":"a"}}\n```\n'
        '```tool_call\n{"name":"Write","arguments":{"file_path":"b","content":"x"}}\n```'
    )
    _app, client, _made = _app_client(tmp_path, reply)

    response = _post(client, {
        "input": "perform both actions",
        "stream": True,
        "tools": [READ_TOOL, WRITE_TOOL],
    })

    assert response.status_code == 200
    events = _events(response)
    assert [event["type"] for event in events] == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert [event["sequence_number"] for event in events] == list(range(len(events)))

    added = [
        event for event in events
        if event["type"] == "response.output_item.added"
    ]
    assert [event["output_index"] for event in added] == [0, 1, 2]
    assert [event["item"]["type"] for event in added] == [
        "message",
        "function_call",
        "function_call",
    ]
    assert [event["item"].get("name") for event in added[1:]] == ["Read", "Write"]
    assert len({event["item"]["id"] for event in added}) == 3
    assert len({event["item"]["call_id"] for event in added[1:]}) == 2

    completed = events[-1]["response"]
    assert [item["type"] for item in completed["output"]] == [
        "message",
        "function_call",
        "function_call",
    ]
    assert completed["output"][0]["content"][0]["text"] == "I'll perform both."
    assert [item["name"] for item in completed["output"][1:]] == ["Read", "Write"]


def test_responses_tool_stream_emits_official_top_level_error_event(tmp_path):
    _app, client, _made = _app_client(
        tmp_path,
        "upstream broke",
        client_type=_FailingStreamClient,
    )

    response = _post(client, {
        "input": "read README",
        "stream": True,
        "tools": [READ_TOOL],
    })

    assert response.status_code == 200
    assert "[DONE]" not in response.text
    events = _events(response)
    assert [event["type"] for event in events] == [
        "response.created",
        "response.in_progress",
        "error",
        "response.failed",
    ]
    assert [event["sequence_number"] for event in events] == [0, 1, 2, 3]
    assert events[2] == {
        "type": "error",
        "code": "server_error",
        "message": "upstream broke",
        "param": None,
        "sequence_number": 2,
    }
    assert events[3]["response"]["status"] == "failed"
    assert events[3]["response"]["error"] == {
        "code": "server_error",
        "message": "upstream broke",
    }
    assert not any(event["type"] == "response.completed" for event in events)


def test_responses_text_stream_marks_throttle_with_official_failed_code(tmp_path):
    _app, client, _made = _app_client(
        tmp_path,
        "upstream result: Throttled",
        client_type=_ThrottledStreamClient,
    )

    response = _post(client, {
        "input": "hello",
        "stream": True,
    })

    assert response.status_code == 200
    events = _events(response)
    error = next(event for event in events if event["type"] == "error")
    failed = next(event for event in events if event["type"] == "response.failed")
    assert error["code"] == "rate_limit_error"
    assert failed["response"]["error"]["code"] == "rate_limit_exceeded"


def test_responses_tool_stream_marks_throttle_with_official_failed_code(tmp_path):
    _app, client, _made = _app_client(
        tmp_path,
        "upstream result: Throttled",
        client_type=_ThrottledStreamClient,
    )

    response = _post(client, {
        "input": "read README",
        "stream": True,
        "tools": [READ_TOOL],
    })

    assert response.status_code == 200
    events = _events(response)
    error = next(event for event in events if event["type"] == "error")
    failed = next(event for event in events if event["type"] == "response.failed")
    assert error["code"] == "rate_limit_error"
    assert failed["response"]["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.parametrize("stream", [False, True])
def test_responses_namespace_function_call_preserves_namespace(tmp_path, stream):
    _app, client, made = _app_client(tmp_path, READ_CALL)

    response = _post(client, {
        "input": "read README",
        "stream": stream,
        "tools": [FILES_NAMESPACE_TOOL],
    })

    assert response.status_code == 200
    if stream:
        events = _events(response)
        added = next(
            event["item"]
            for event in events
            if event["type"] == "response.output_item.added"
            and event["item"]["type"] == "function_call"
        )
        calls = [
            item
            for item in events[-1]["response"]["output"]
            if item["type"] == "function_call"
        ]
        assert added["namespace"] == "filesystem"
    else:
        calls = [
            item
            for item in response.json()["output"]
            if item["type"] == "function_call"
        ]
    assert [(call["namespace"], call["name"]) for call in calls] == [
        ("filesystem", "Read")
    ]
    upstream_context = "\n".join(made[-1].calls[0][1])
    assert "namespace filesystem" in upstream_context.lower()


def test_responses_namespace_strict_function_schema_is_enforced(tmp_path):
    namespace = {
        **FILES_NAMESPACE_TOOL,
        "tools": [{**READ_TOOL, "strict": True}],
    }
    _app, client, _made = _app_client(tmp_path, INVALID_STRICT_READ_CALL)

    response = _post(client, {
        "input": "read README",
        "tools": [namespace],
    })

    assert response.status_code == 200
    assert not [
        item for item in response.json()["output"]
        if item["type"] == "function_call"
    ]


def test_responses_namespace_is_preserved_in_function_history():
    request = OpenAIResponsesRequest.model_validate({
        "model": "copilot-reasoning",
        "input": [
            {
                "type": "function_call",
                "call_id": "call_123",
                "namespace": "filesystem",
                "name": "Read",
                "arguments": '{"file_path":"README.md"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_123",
                "output": "README contents",
            },
        ],
        "tools": [FILES_NAMESPACE_TOOL],
    })

    translated = translate_responses_request(request)

    transcript = _context(translated, "Prior conversation transcript:\n")
    assert "filesystem.Read" in transcript
    assert "README contents" in transcript


def test_responses_rejects_ambiguous_namespace_function_names(tmp_path):
    _app, client, made = _app_client(tmp_path, "unused")
    second_namespace = {
        **FILES_NAMESPACE_TOOL,
        "name": "workspace",
    }

    response = _post(client, {
        "input": "read README",
        "tools": [FILES_NAMESPACE_TOOL, second_namespace],
    })

    assert response.status_code == 400
    assert "duplicate function name" in response.text.lower()
    assert not made or made[-1].calls == []


def test_responses_rejects_duplicate_flat_function_names(tmp_path):
    _app, client, made = _app_client(tmp_path, "unused")

    response = _post(client, {
        "input": "read README",
        "tools": [READ_TOOL, READ_TOOL],
    })

    assert response.status_code == 400
    assert "duplicate function name" in response.text.lower()
    assert not made or made[-1].calls == []


def test_responses_rejects_non_function_inside_namespace(tmp_path):
    _app, client, made = _app_client(tmp_path, "unused")
    namespace = {
        **FILES_NAMESPACE_TOOL,
        "tools": [{"type": "custom", "name": "shell"}],
    }

    response = _post(client, {
        "input": "run a tool",
        "tools": [namespace],
    })

    assert response.status_code == 400
    assert "namespace tools must contain only function tools" in response.text.lower()
    assert not made or made[-1].calls == []


def test_codex_shaped_tools_still_reject_web_search_before_upstream(tmp_path):
    _app, client, made = _app_client(tmp_path, "unused")

    response = _post(client, {
        "input": "inspect the repository",
        "tools": [WRITE_TOOL, FILES_NAMESPACE_TOOL, {"type": "web_search"}],
    })

    assert response.status_code == 400
    assert "only function tools are supported" in response.text
    assert not made or made[-1].calls == []


# --- NO_TOOL_NEEDED on this surface too ------------------------------------
#
# The contract translate_responses_request injects asks the model to end a
# no-action turn with the token (translator.py:381), so a declined turn is a
# shape this surface really produces. Both call sites here used to drop the flag
# (raw_text, _declined = ...), and the resolver took no declined parameter at
# all, so its prose fallback ran anyway: a reply that says "put this in
# `S:/tmp/demo.py` yourself" plus a python block became a fabricated Write for a
# file the model had just declined to write. chat and /v1/messages never had this
# because both thread declined into the resolver.
DECLINED_PROSE = (
    "You can paste it into `S:/tmp/demo.py` yourself:\n\n"
    "```python\nprint(1)\n```\n\n"
    "NO_TOOL_NEEDED"
)
UNDECLINED_PROSE = DECLINED_PROSE.replace("\n\nNO_TOOL_NEEDED", "")


def _responses_output_names(response):
    return [item["type"] for item in response.json()["output"]]


def _responses_output_text(response):
    return "".join(
        part.get("text") or ""
        for item in response.json()["output"]
        if item.get("type") == "message"
        for part in item.get("content") or []
    )


def _stream_item_types(response):
    return [
        event["item"].get("type")
        for event in _events(response)
        if event.get("type") == "response.output_item.added"
    ]


def _stream_text(response):
    return "".join(
        event.get("delta") or ""
        for event in _events(response)
        if event.get("type") == "response.output_text.delta"
    )


@pytest.mark.parametrize("stream", [False, True])
def test_responses_declined_turn_does_not_fabricate_a_prose_write(tmp_path, stream):
    """An explicit no-action answer must not be turned into a Write.

    The prose fallback exists for a model that meant to write a file and
    described it instead of calling the tool. A model that ended with the token
    answered the contract, so synthesizing a call here invents a file write the
    user never got -- and the client would report success for it.
    """
    _app, client, _made = _app_client(tmp_path, DECLINED_PROSE)

    response = _post(client, {
        "input": "how do I save this snippet?",
        "tools": [WRITE_TOOL],
        "stream": stream,
    })

    assert response.status_code == 200
    if stream:
        assert "function_call" not in _stream_item_types(response)
        text = _stream_text(response)
    else:
        assert "function_call" not in _responses_output_names(response)
        text = _responses_output_text(response)
    assert "demo.py" in text
    # The token is protocol chatter between host and model, never user-facing.
    assert "NO_TOOL_NEEDED" not in text


@pytest.mark.parametrize("stream", [False, True])
def test_responses_prose_write_still_fires_without_the_token(tmp_path, stream):
    """The positive control: the fix must not disable the fallback outright.

    Same reply minus the token is the case the fallback was built for, so it has
    to still synthesize the call -- otherwise the test above would pass just as
    well with _extract_prose_write deleted.
    """
    _app, client, _made = _app_client(tmp_path, UNDECLINED_PROSE)

    response = _post(client, {
        "input": "how do I save this snippet?",
        "tools": [WRITE_TOOL],
        "stream": stream,
    })

    assert response.status_code == 200
    if stream:
        assert "function_call" in _stream_item_types(response)
    else:
        assert "function_call" in _responses_output_names(response)


# The other half of the same alignment: the corrective "you claimed a file but
# emitted no tool_call" retry. chat (routes_api_chat.py:571, :860) and /v1/messages
# (routes_api_messages.py:545, :752) have always had `and not declined` in that
# condition; this surface did not, so a declined turn that happens to word itself
# with 已生成 spent a second upstream turn -- on consumer that is a real quota unit.
FAKE_CLAIM_DECLINED = "已生成 S:/tmp/report.md 了，你自己保存一下。\n\nNO_TOOL_NEEDED"
FAKE_CLAIM = FAKE_CLAIM_DECLINED.replace("\n\nNO_TOOL_NEEDED", "")


def _upstream_calls(made) -> int:
    return sum(len(client.calls) for client in made)


@pytest.mark.parametrize("stream", [False, True])
def test_responses_declined_turn_skips_the_corrective_file_retry(tmp_path, stream):
    _app, client, made = _app_client(tmp_path, FAKE_CLAIM_DECLINED)

    response = _post(client, {
        "input": "write the report",
        "tools": [WRITE_TOOL],
        "stream": stream,
    })

    assert response.status_code == 200
    assert _upstream_calls(made) == 1


@pytest.mark.parametrize("stream", [False, True])
def test_responses_undeclined_fake_claim_still_retries(tmp_path, stream):
    """Positive control: the phrase branch is live, so the test above measures the
    declined flag and not a claim that failed to be recognised."""
    _app, client, made = _app_client(tmp_path, FAKE_CLAIM)

    response = _post(client, {
        "input": "write the report",
        "tools": [WRITE_TOOL],
        "stream": stream,
    })

    assert response.status_code == 200
    assert _upstream_calls(made) == 2
