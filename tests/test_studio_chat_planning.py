from __future__ import annotations

import base64
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.models import OpenAIChatRequest, OpenAIMessage
from m365_copilot_openai_proxy.routes_api_chat import _openai_stream_with_tools
from m365_copilot_openai_proxy.sse_stream import keepalive_stream
from m365_copilot_openai_proxy.usage_store import estimate_upstream_input_tokens
from m365_copilot_openai_proxy.session_helpers import (
    _namespaced_session,
    _persistent_session,
    _studio_session_namespace,
)
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotError
from m365_copilot_openai_proxy.studio_planner import STUDIO_TONE
from m365_copilot_openai_proxy.tone_options import router_applies, tool_planning_mode


AGENT_ID = "title.bot.gpt.default"
OTHER_AGENT_ID = "other.bot.gpt.default"
READ_CALL = (
    '```tool_call\n'
    '{"name":"Read","arguments":{"file_path":"/tmp/a.txt"}}'
    '\n```'
)
NATIVE_FILE_REPLY = "Created the file: https://example.test/demo.py"
READ_TOOL = {
    "type": "function",
    "function": {
        "name": "Read",
        "description": "Read a file",
        "parameters": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
}
RESPONSES_READ_TOOL = {
    "type": "function",
    "name": "Read",
    "description": "Read a file",
    "parameters": READ_TOOL["function"]["parameters"],
}


def _jwt(tid: str = "tenant-a", oid: str = "object-a") -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({
        "aud": "https://substrate.office.com/",
        "tid": tid,
        "oid": oid,
        "exp": int(time.time()) + 3600,
    }).encode()).decode().rstrip("=")
    return f"{header}.{payload}."


class RecordingClient:
    def __init__(
        self,
        *,
        token: str = "",
        studio_agent_id: str = "",
        fail: bool = False,
        outputs: list[str] | None = None,
        reserve_before_failure: bool = False,
    ):
        self.token = token
        self.studio_agent_id = studio_agent_id
        self.fail = fail
        self.outputs = list(outputs or [])
        self.reserve_before_failure = reserve_before_failure
        self.calls: list[tuple[str, object]] = []
        self.contexts: list[list[str]] = []
        self._tone = "Magic"

    async def chat(self, prompt, context=None, session=None, images=None):
        return "".join(
            [part async for part in self.chat_stream(prompt, context, session, images)]
        )

    async def chat_stream(self, prompt, context=None, session=None, images=None):
        self.calls.append((prompt, session))
        self.contexts.append(list(context or []))
        if self.reserve_before_failure and session is not None:
            session.reserve_turn()
        if self.fail:
            raise SubstrateCopilotError("studio failed")
        if self.outputs:
            yield self.outputs.pop(0)
            return
        if "You are a tool-use router" in prompt:
            yield 'CALL_TOOL: Read({"file_path":"/tmp/a.txt"})'
        else:
            yield READ_CALL


def _app(
    tmp_path,
    *,
    provider: str = "m365",
    ready: bool = True,
    fail_studio: bool = False,
    studio_outputs: list[str] | None = None,
    ordinary_outputs: list[str] | None = None,
    reserve_studio_turn_before_failure: bool = False,
):
    made: list[RecordingClient] = []

    def factory(**kwargs):
        client = RecordingClient(
            token=str(kwargs.get("token") or ""),
            studio_agent_id=str(kwargs.get("studio_agent_id") or ""),
            fail=bool(kwargs.get("studio_agent_id")) and fail_studio,
            outputs=(
                studio_outputs
                if bool(kwargs.get("studio_agent_id"))
                else ordinary_outputs
            ),
            reserve_before_failure=(
                bool(kwargs.get("studio_agent_id"))
                and reserve_studio_turn_before_failure
            ),
        )
        made.append(client)
        return client

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""),
        copilot_client_factory=factory,
    )
    account = app.state.account_store.add(name="Studio", token=_jwt())
    if provider == "consumer":
        app.state.account_store.set_consumer_auth(
            account.id,
            cookies=[],
            access_token="consumer-token",
        )
        app.state.consumer_client_factory = lambda **kwargs: RecordingClient()
    elif ready:
        app.state.account_store.set_studio_agent_id(account.id, AGENT_ID)
    key = app.state.key_store.add(name="Studio Key", account_id=account.id)
    app.state.key_store.update(key.id, tool_planning_mode="studio")
    client = TestClient(app)
    return app, client, key.key, made


def _chat(
    client: TestClient,
    key: str,
    *,
    stream: bool = False,
    tools=True,
    model: str = "m365-copilot",
):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "read /tmp/a.txt"}],
        "stream": stream,
    }
    if tools:
        body["tools"] = [READ_TOOL]
    return client.post(
        "/v1/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {key}"},
    )


def _responses_body(response, stream: bool) -> dict:
    if not stream:
        return response.json()
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    return next(
        event["response"]
        for event in events
        if event.get("type") == "response.completed"
    )


def _anthropic_tool_use(response, stream: bool) -> dict:
    if not stream:
        return next(
            item for item in response.json()["content"] if item["type"] == "tool_use"
        )
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    return next(
        event["content_block"]
        for event in events
        if event.get("type") == "content_block_start"
        and event.get("content_block", {}).get("type") == "tool_use"
    )


class ContextAwareResponsesClient:
    _tone = "Magic"

    def __init__(self):
        self.calls: list[tuple[str, str, list[str], object]] = []

    def _reply(self, prompt: str) -> str:
        if "You are a tool-use router" in prompt:
            if "tool-result-sentinel" not in prompt:
                return 'CALL_TOOL: Read({"file_path":"/tmp/context.txt"})'
            return (
                "NO_TOOL_NEEDED"
                if "original-task-sentinel" in prompt
                else 'CALL_TOOL: Read({"file_path":"/tmp/context.txt"})'
            )
        return "final-answer-sentinel"

    async def chat(self, prompt, context=None, session=None, images=None):
        self.calls.append(("chat", prompt, list(context or []), session))
        if session is not None:
            session.reserve_turn()
        return self._reply(prompt)

    async def chat_stream(self, prompt, context=None, session=None, images=None):
        self.calls.append(("stream", prompt, list(context or []), session))
        if session is not None:
            session.reserve_turn()
        yield self._reply(prompt)


class StudioResponsesContinuationClient:
    """Return a tool call once, then answer after the host submits its result."""

    def __init__(self, *, studio: bool):
        self.studio = studio
        self.calls: list[tuple[str, str, list[str], object]] = []

    async def chat(self, prompt, context=None, session=None, images=None):
        chunks = [
            item
            async for item in self.chat_stream(prompt, context, session, images)
        ]
        return "".join(chunks)

    async def chat_stream(self, prompt, context=None, session=None, images=None):
        context = list(context or [])
        self.calls.append(("stream", prompt, context, session))
        if session is not None:
            session.reserve_turn()
        if any("Tool: Tool result" in item for item in context):
            yield "studio-final-answer"
        else:
            yield READ_CALL


class FailingStudioContinuationClient:
    studio = True

    def __init__(self):
        self.calls: list[tuple[str, str, list[str], object]] = []

    async def chat_stream(self, prompt, context=None, session=None, images=None):
        self.calls.append(("stream", prompt, list(context or []), session))
        if session is not None:
            session.reserve_turn()
        raise SubstrateCopilotError("studio continuation failed")
        yield  # pragma: no cover - keep this an async generator


class StudioTextThenFailClient:
    studio = True

    def __init__(self, *, fail: bool):
        self.fail = fail
        self.calls: list[tuple[str, str, list[str], object]] = []

    async def chat(self, prompt, context=None, session=None, images=None):
        return "".join([
            item
            async for item in self.chat_stream(prompt, context, session, images)
        ])

    async def chat_stream(self, prompt, context=None, session=None, images=None):
        self.calls.append(("stream", prompt, list(context or []), session))
        if session is not None:
            session.reserve_turn()
        if self.fail:
            raise SubstrateCopilotError("studio text continuation failed")
        yield "studio-text-sentinel"


def _custom_studio_app(tmp_path, client_factory):
    made = []

    def factory(**_kwargs):
        client = client_factory()
        made.append(client)
        return client

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""),
        copilot_client_factory=factory,
    )
    account = app.state.account_store.add(name="Studio", token=_jwt())
    app.state.account_store.set_studio_agent_id(account.id, AGENT_ID)
    key = app.state.key_store.add(name="Studio Key", account_id=account.id)
    app.state.key_store.update(key.id, tool_planning_mode="studio")
    return app, TestClient(app), key.key, made


def _studio_responses_continuation_app(tmp_path):
    made = []

    def factory(**kwargs):
        client = StudioResponsesContinuationClient(
            studio=bool(kwargs.get("studio_agent_id"))
        )
        made.append(client)
        return client

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""),
        copilot_client_factory=factory,
    )
    account = app.state.account_store.add(name="Studio", token=_jwt())
    app.state.account_store.set_studio_agent_id(account.id, AGENT_ID)
    key = app.state.key_store.add(name="Studio Key", account_id=account.id)
    app.state.key_store.update(key.id, tool_planning_mode="studio")
    return app, TestClient(app), key.key, made


def _studio_continuation_fallback_app(tmp_path):
    made = []
    studio_calls = 0

    def factory(**kwargs):
        nonlocal studio_calls
        if kwargs.get("studio_agent_id"):
            studio_calls += 1
            client = (
                StudioResponsesContinuationClient(studio=True)
                if studio_calls == 1
                else FailingStudioContinuationClient()
            )
        else:
            client = ContextAwareResponsesClient()
        made.append(client)
        return client

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""),
        copilot_client_factory=factory,
    )
    account = app.state.account_store.add(name="Studio", token=_jwt())
    app.state.account_store.set_studio_agent_id(account.id, AGENT_ID)
    key = app.state.key_store.add(name="Studio Key", account_id=account.id)
    app.state.key_store.update(key.id, tool_planning_mode="studio")
    return app, TestClient(app), key.key, made


def _studio_text_continuation_fallback_app(tmp_path):
    made = []
    studio_calls = 0

    def factory(**kwargs):
        nonlocal studio_calls
        if kwargs.get("studio_agent_id"):
            studio_calls += 1
            client = StudioTextThenFailClient(fail=studio_calls > 1)
        else:
            client = ContextAwareResponsesClient()
        made.append(client)
        return client

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""),
        copilot_client_factory=factory,
    )
    account = app.state.account_store.add(name="Studio", token=_jwt())
    app.state.account_store.set_studio_agent_id(account.id, AGENT_ID)
    key = app.state.key_store.add(name="Studio Key", account_id=account.id)
    app.state.key_store.update(key.id, tool_planning_mode="studio")
    return app, TestClient(app), key.key, made


@pytest.mark.parametrize("raw", ["studio", " STUDIO "])
def test_studio_is_a_valid_planning_mode(raw):
    assert tool_planning_mode(raw) == "studio"
    assert router_applies(raw, "Claude_Sonnet") is True


def test_studio_namespace_uses_a_distinct_session_key(tmp_path):
    app, _client, key, _made = _app(tmp_path)
    key_obj = app.state.key_store.resolve(key)
    account = app.state.account_store.get(key_obj.account_id)
    raw = type("Raw", (), {
        "headers": {"x-m365-session-id": "same"},
        "state": type("State", (), {"api_key_obj": key_obj, "account": account})(),
    })()
    request = OpenAIChatRequest(
        model="m365-copilot",
        messages=[OpenAIMessage(role="user", content="hello")],
    )

    normal = _persistent_session(app, raw, request.model, request=request)
    studio = _persistent_session(
        app, raw, request.model, request=request, namespace="studio"
    )

    assert app.state.session_store.key_for(normal) != app.state.session_store.key_for(studio)


def test_namespaced_session_mirrors_existing_response_session_key(tmp_path):
    app, _client, key, _made = _app(tmp_path)
    key_obj = app.state.key_store.resolve(key)
    account = app.state.account_store.get(key_obj.account_id)
    raw = type("Raw", (), {
        "headers": {},
        "state": type("State", (), {"api_key_obj": key_obj, "account": account})(),
    })()
    normal = app.state.session_store.get(
        f"{key_obj.id}:{account.id}:auto:responses_123"
    )

    studio = _namespaced_session(app, raw, normal, "studio")

    assert app.state.session_store.key_for(studio) == (
        f"{key_obj.id}:{account.id}:studio:auto:responses_123"
    )


def test_studio_agent_namespace_changes_when_agent_is_rebound(tmp_path):
    app, _client, key, _made = _app(tmp_path)
    key_obj = app.state.key_store.resolve(key)
    account = app.state.account_store.get(key_obj.account_id)
    raw = type("Raw", (), {
        "headers": {"x-m365-session-id": "same"},
        "state": type("State", (), {"api_key_obj": key_obj, "account": account})(),
    })()
    request = OpenAIChatRequest(
        model="m365-copilot",
        messages=[OpenAIMessage(role="user", content="hello")],
    )

    first = _persistent_session(
        app,
        raw,
        request.model,
        request=request,
        namespace=_studio_session_namespace(AGENT_ID),
    )
    second = _persistent_session(
        app,
        raw,
        request.model,
        request=request,
        namespace=_studio_session_namespace(OTHER_AGENT_ID),
    )

    assert first.conversation_id != second.conversation_id
    first_key = app.state.session_store.key_for(first)
    second_key = app.state.session_store.key_for(second)
    assert AGENT_ID not in first_key
    assert OTHER_AGENT_ID not in second_key
    assert first_key != second_key


def test_ready_m365_tools_chat_uses_bound_studio_client(tmp_path, caplog):
    app, client, key, made = _app(tmp_path)

    with caplog.at_level("WARNING", logger="copilot_proxy"):
        response = _chat(client, key)

    assert response.status_code == 200
    assert response.headers["X-M365-Tool-Calling"] == "studio"
    assert [call["function"]["name"] for call in response.json()["choices"][0]["message"]["tool_calls"]] == ["Read"]
    assert [item.studio_agent_id for item in made] == ["", AGENT_ID]
    assert len(made[0].calls) == 0
    assert len(made[1].calls) == 1
    record = app.state.call_log[-1]
    assert record["tool_planning"] == "studio"
    assert "studio_fallback" not in record
    assert AGENT_ID not in json.dumps(record)
    assert "planning this turn with a router turn instead" not in caplog.text


def test_studio_planner_uses_compatible_tone_for_claude_request(tmp_path):
    app, client, key, made = _app(tmp_path)

    response = _chat(client, key, model="claude-sonnet-4-6")

    assert response.status_code == 200
    assert made[-1]._tone == STUDIO_TONE
    assert app.state.call_log[-1]["tone"] == "Claude_Sonnet"
    assert app.state.call_log[-1]["tool_planning"] == "studio"


def test_ready_m365_stream_uses_studio_and_reports_actual_header(tmp_path):
    app, client, key, made = _app(tmp_path)

    response = _chat(client, key, stream=True)

    assert response.status_code == 200
    assert response.headers["X-M365-Tool-Calling"] == "studio"
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert '"name": "Read"' in response.text
    assert [item.studio_agent_id for item in made] == ["", AGENT_ID]
    assert app.state.call_log[-1]["tool_planning"] == "studio"


def test_zero_output_studio_error_falls_back_to_router_and_updates_metadata(tmp_path):
    app, client, key, made = _app(tmp_path, fail_studio=True)

    response = _chat(client, key)

    assert response.status_code == 200
    assert response.headers["X-M365-Tool-Calling"] == "router"
    assert [item.studio_agent_id for item in made] == ["", AGENT_ID]
    assert len(made[0].calls) == 1
    record = app.state.call_log[-1]
    assert record["tool_planning"] == "router"
    assert record["studio_fallback"] == "upstream_error"


def test_stream_zero_output_studio_error_records_router_after_fallback(tmp_path):
    app, client, key, made = _app(tmp_path, fail_studio=True)

    response = _chat(client, key, stream=True)

    assert response.status_code == 200
    assert response.headers["X-M365-Tool-Calling"] == "studio"
    assert len(made[0].calls) == 1
    assert app.state.call_log[-1]["studio_fallback"] == "upstream_error"
    persisted = json.loads(app.state.call_log_path.read_text(encoding="utf-8"))[-1]
    assert persisted["tool_planning"] == "router"
    assert persisted["studio_fallback"] == "upstream_error"


def test_chat_tool_stream_emits_keepalive_before_slow_studio_finishes():
    class SlowClient:
        async def chat_stream(self, prompt, context=None, session=None, images=None):
            await asyncio.sleep(0.05)
            yield READ_CALL

    async def run():
        stream = keepalive_stream(
            _openai_stream_with_tools(
                "m365-copilot",
                SlowClient(),
                "read /tmp/a.txt",
                [],
                tool_names={"Read"},
            ),
            interval=0.001,
        )
        return await asyncio.wait_for(anext(stream), timeout=0.02)

    assert asyncio.run(run()) == ": keepalive\n\n"


@pytest.mark.parametrize("stream", [False, True])
def test_studio_corrective_retry_reuses_studio_client_and_session(stream, tmp_path):
    app, client, key, made = _app(
        tmp_path,
        studio_outputs=[NATIVE_FILE_REPLY, READ_CALL],
    )

    response = _chat(client, key, stream=stream)

    assert response.status_code == 200
    assert len(made) == 2
    assert made[0].calls == []
    assert len(made[1].calls) == 2
    assert made[1].calls[0][1] is made[1].calls[1][1]
    assert app.state.call_log[-1]["retried"] is True


@pytest.mark.parametrize(
    "provider,ready,reason",
    [("m365", False, "not_ready"), ("consumer", False, "unsupported_provider")],
)
def test_unavailable_studio_chat_uses_router(
    provider, ready, reason, tmp_path, caplog
):
    app, client, key, made = _app(tmp_path, provider=provider, ready=ready)

    with caplog.at_level("WARNING", logger="copilot_proxy"):
        response = _chat(
            client,
            key,
            model="copilot" if provider == "consumer" else "m365-copilot",
        )

    assert response.status_code == 200
    assert response.headers["X-M365-Tool-Calling"] == "router"
    assert not [item for item in made if item.studio_agent_id]
    record = app.state.call_log[-1]
    assert record["tool_planning"] == "router"
    assert record["studio_fallback"] == reason
    assert "planning this turn with a router turn instead" in caplog.text


def test_studio_mode_without_tools_keeps_the_ordinary_path(tmp_path):
    app, client, key, made = _app(tmp_path)

    response = _chat(client, key, tools=False)

    assert response.status_code == 200
    assert "X-M365-Tool-Calling" not in response.headers
    assert [item.studio_agent_id for item in made] == [""]
    assert "studio_fallback" not in app.state.call_log[-1]


@pytest.mark.parametrize(
    "endpoint,headers,body",
    [
        (
            "/v1/messages",
            {"x-api-key": "{key}"},
            {
                "model": "m365-copilot",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": "read /tmp/a.txt"}],
                "tools": [{
                    "name": "Read",
                    "description": "Read a file",
                    "input_schema": READ_TOOL["function"]["parameters"],
                }],
            },
        ),
        (
            "/v1/responses",
            {"Authorization": "Bearer {key}"},
            {
                "model": "m365-copilot",
                "input": "read /tmp/a.txt",
                "tools": [RESPONSES_READ_TOOL],
            },
        ),
    ],
)
def test_other_tool_endpoints_use_bound_studio_client(
    endpoint, headers, body, tmp_path
):
    app, client, key, made = _app(tmp_path)

    response = client.post(
        endpoint,
        json=body,
        headers={name: value.format(key=key) for name, value in headers.items()},
    )

    assert response.status_code == 200
    assert [item.studio_agent_id for item in made] == ["", AGENT_ID]
    assert not made[0].calls
    assert made[1].calls
    assert "You are a tool-use router" not in made[1].calls[0][0]
    record = app.state.call_log[-1]
    assert record["tool_planning"] == "studio"
    assert "studio_fallback" not in record


def test_responses_stream_studio_mode_uses_bound_studio_client(tmp_path):
    app, client, key, made = _app(tmp_path)

    response = client.post(
        "/v1/responses",
        json={
            "model": "m365-copilot",
            "input": "read /tmp/a.txt",
            "stream": True,
            "tools": [RESPONSES_READ_TOOL],
        },
        headers={"Authorization": f"Bearer {key}"},
    )

    assert response.status_code == 200
    assert '"name": "Read"' in response.text
    assert [item.studio_agent_id for item in made] == ["", AGENT_ID]
    assert not made[0].calls
    assert "You are a tool-use router" not in made[1].calls[0][0]
    record = app.state.call_log[-1]
    assert record["tool_planning"] == "studio"
    assert "studio_fallback" not in record


@pytest.mark.parametrize("stream", [False, True])
def test_responses_studio_tool_continuation_reuses_studio_namespace(
    stream, tmp_path
):
    app, client, key, made = _studio_responses_continuation_app(tmp_path)
    first = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "input": "read /tmp/a.txt",
            "stream": stream,
            "tools": [RESPONSES_READ_TOOL],
        },
    )

    assert first.status_code == 200
    first_body = _responses_body(first, stream)
    call = next(item for item in first_body["output"] if item["type"] == "function_call")
    continued = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "previous_response_id": first_body["id"],
            "input": [{
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": "contents of /tmp/a.txt",
            }],
            "stream": stream,
            "tools": [RESPONSES_READ_TOOL],
        },
    )

    assert continued.status_code == 200
    continued_body = _responses_body(continued, stream)
    assert "studio-final-answer" in json.dumps(continued_body)
    assert app.state.call_log[-1]["tool_planning"] == "studio"
    studio_clients = [item for item in made if item.studio]
    assert len(studio_clients) == 2
    assert studio_clients[0].calls[0][3] is studio_clients[1].calls[0][3]
    assert any("Tool: Tool result" in item for item in studio_clients[1].calls[0][2])


@pytest.mark.parametrize("stream", [False, True])
def test_chat_studio_tool_continuation_accepts_final_answer(stream, tmp_path):
    app, client, key, made = _studio_responses_continuation_app(tmp_path)
    first = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "messages": [{"role": "user", "content": "read /tmp/a.txt"}],
            "stream": stream,
            "tools": [READ_TOOL],
        },
    )

    assert first.status_code == 200
    if stream:
        chunks = [
            json.loads(line.removeprefix("data: "))
            for line in first.text.splitlines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        tool_call = next(
            call
            for chunk in chunks
            for choice in chunk.get("choices", [])
            for call in choice.get("delta", {}).get("tool_calls", [])
            if call.get("function", {}).get("name")
        )
    else:
        tool_call = first.json()["choices"][0]["message"]["tool_calls"][0]

    continued = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "messages": [
                {"role": "user", "content": "read /tmp/a.txt"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tool_call],
                },
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": "contents of /tmp/a.txt",
                },
            ],
            "stream": stream,
            "tools": [READ_TOOL],
        },
    )

    assert continued.status_code == 200
    assert "studio-final-answer" in continued.text
    assert app.state.call_log[-1]["tool_planning"] == "studio"
    studio_clients = [item for item in made if item.studio]
    assert len(studio_clients) == 2
    assert studio_clients[0].calls[0][3] is studio_clients[1].calls[0][3]


@pytest.mark.parametrize("stream", [False, True])
def test_responses_studio_full_history_continuation_sends_only_new_turn(
    stream, tmp_path
):
    app, client, key, made = _studio_responses_continuation_app(tmp_path)
    first = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "input": "responses-original-task-sentinel",
            "stream": stream,
            "tools": [RESPONSES_READ_TOOL],
        },
    )

    assert first.status_code == 200
    first_body = _responses_body(first, stream)
    call = next(item for item in first_body["output"] if item["type"] == "function_call")
    continued = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "previous_response_id": first_body["id"],
            "input": [
                {"role": "user", "content": "responses-original-task-sentinel"},
                {
                    "type": "function_call",
                    "call_id": call["call_id"],
                    "name": call["name"],
                    "arguments": call["arguments"],
                },
                {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": "responses-tool-result-sentinel",
                },
            ],
            "stream": stream,
            "tools": [RESPONSES_READ_TOOL],
        },
    )

    assert continued.status_code == 200
    studio_clients = [item for item in made if item.studio]
    assert len(studio_clients) == 2
    continuation_context = "\n".join(studio_clients[1].calls[0][2])
    assert "responses-tool-result-sentinel" in continuation_context
    assert "responses-original-task-sentinel" not in continuation_context
    assert "Assistant called tool" not in continuation_context


def test_responses_studio_continuation_usage_matches_incremental_payload(tmp_path):
    app, client, key, made = _studio_responses_continuation_app(tmp_path)
    first = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "input": "responses-original-task-sentinel",
            "tools": [RESPONSES_READ_TOOL],
        },
    )
    assert first.status_code == 200
    first_body = first.json()
    call = next(item for item in first_body["output"] if item["type"] == "function_call")
    continued = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "previous_response_id": first_body["id"],
            "input": [
                {"role": "user", "content": "responses-original-task-sentinel"},
                {"type": "function_call", "call_id": call["call_id"], "name": call["name"], "arguments": call["arguments"]},
                {"type": "function_call_output", "call_id": call["call_id"], "output": "responses-tool-result-sentinel"},
            ],
            "tools": [RESPONSES_READ_TOOL],
        },
    )
    assert continued.status_code == 200
    studio_clients = [item for item in made if item.studio]
    prompt, context, _session = studio_clients[1].calls[0][1:]
    expected = estimate_upstream_input_tokens(prompt, context)
    assert app.state.call_log[-1]["usage_input_tokens"] == expected


@pytest.mark.parametrize("stream", [False, True])
def test_anthropic_studio_tool_continuation_reuses_studio_namespace(
    stream, tmp_path
):
    app, client, key, made = _studio_responses_continuation_app(tmp_path)
    first = client.post(
        "/v1/messages",
        headers={"x-api-key": key},
        json={
            "model": "m365-copilot",
            "max_tokens": 256,
            "stream": stream,
            "messages": [{"role": "user", "content": "read /tmp/a.txt"}],
            "tools": [{
                "name": "Read",
                "description": "Read a file",
                "input_schema": READ_TOOL["function"]["parameters"],
            }],
        },
    )

    assert first.status_code == 200
    tool_use = _anthropic_tool_use(first, stream)
    continued = client.post(
        "/v1/messages",
        headers={"x-api-key": key},
        json={
            "model": "m365-copilot",
            "max_tokens": 256,
            "stream": stream,
            "messages": [
                {"role": "user", "content": "read /tmp/a.txt"},
                {"role": "assistant", "content": [tool_use]},
                {
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_use["id"],
                        "content": "contents of /tmp/a.txt",
                    }],
                },
            ],
            "tools": [{
                "name": "Read",
                "description": "Read a file",
                "input_schema": READ_TOOL["function"]["parameters"],
            }],
        },
    )

    assert continued.status_code == 200
    assert "studio-final-answer" in continued.text
    assert app.state.call_log[-1]["tool_planning"] == "studio"
    studio_clients = [item for item in made if item.studio]
    assert len(studio_clients) == 2
    assert studio_clients[0].calls[0][3] is studio_clients[1].calls[0][3]
    continuation_context = "\n".join(studio_clients[1].calls[0][2])
    assert "Tool result" in continuation_context
    assert "contents of /tmp/a.txt" in continuation_context
    assert "User: read /tmp/a.txt" not in continuation_context
    assert "Assistant called tool: Read" not in continuation_context


@pytest.mark.parametrize("stream", [False, True])
def test_responses_studio_continuation_fallback_router_sees_original_task(
    stream, tmp_path
):
    app, client, key, made = _studio_continuation_fallback_app(tmp_path)
    first = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "input": "original-task-sentinel: inspect /tmp/context.txt",
            "stream": stream,
            "tools": [RESPONSES_READ_TOOL],
        },
    )

    assert first.status_code == 200
    first_body = _responses_body(first, stream)
    call = next(item for item in first_body["output"] if item["type"] == "function_call")
    continued = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "previous_response_id": first_body["id"],
            "input": [{
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": "tool-result-sentinel",
            }],
            "stream": stream,
            "tools": [RESPONSES_READ_TOOL],
        },
    )

    assert continued.status_code == 200
    body = _responses_body(continued, stream)
    assert not [item for item in body["output"] if item["type"] == "function_call"]
    assert "final-answer-sentinel" in json.dumps(body)
    router_calls = [
        call
        for client_obj in made
        for call in client_obj.calls
        if "You are a tool-use router" in call[1]
    ]
    assert not router_calls
    assert app.state.call_log[-1]["tool_planning"] == "inline"
    assert app.state.call_log[-1]["studio_fallback"] == "upstream_error"


@pytest.mark.parametrize("stream", [False, True])
def test_responses_text_continuation_after_tool_call_is_rejected(
    stream, tmp_path
):
    app, client, key, made = _studio_text_continuation_fallback_app(tmp_path)
    first = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "input": "original-task-sentinel: remember this task",
            "stream": stream,
            "tools": [RESPONSES_READ_TOOL],
        },
    )

    assert first.status_code == 200
    first_body = _responses_body(first, stream)
    # The initial Studio answer is a no-call planner result, so the configured
    # Studio -> Router fallback produces the actual tool decision.
    assert "studio-text-sentinel" not in json.dumps(first_body)
    assert [item for item in first_body["output"] if item["type"] == "function_call"]

    continued = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "previous_response_id": first_body["id"],
            "input": "follow-up-sentinel",
            "stream": stream,
            "tools": [RESPONSES_READ_TOOL],
        },
    )

    assert continued.status_code == 400
    assert "function_call_output" in continued.text


@pytest.mark.parametrize("stream", [False, True])
def test_responses_router_tool_continuation_restores_original_task_context(
    stream, tmp_path
):
    app, client, key, made = _custom_studio_app(
        tmp_path, ContextAwareResponsesClient
    )
    app.state.key_store.update(
        app.state.key_store.resolve(key).id, tool_planning_mode="router"
    )
    first = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "input": "original-task-sentinel: inspect /tmp/context.txt",
            "stream": stream,
            "tools": [RESPONSES_READ_TOOL],
        },
    )
    assert first.status_code == 200
    first_body = _responses_body(first, stream)
    call = next(
        item for item in first_body["output"] if item["type"] == "function_call"
    )

    continued = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "previous_response_id": first_body["id"],
            "input": [{
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": "tool-result-sentinel",
            }],
            "stream": stream,
            "tools": [RESPONSES_READ_TOOL],
        },
    )

    assert continued.status_code == 200
    continued_body = _responses_body(continued, stream)
    assert not [
        item for item in continued_body["output"] if item["type"] == "function_call"
    ]
    assert "final-answer-sentinel" in json.dumps(continued_body)
    router_calls = [
        call
        for client_obj in made
        for call in client_obj.calls
        if "You are a tool-use router" in call[1]
    ]
    # The first turn needs one classifier pass. A function_call_output
    # continuation is already in the router namespace and must answer directly.
    assert len(router_calls) == 1
    answer_call = next(
        call
        for client_obj in reversed(made)
        for call in reversed(client_obj.calls)
        if "You are a tool-use router" not in call[1]
    )
    restored_context = "\n".join(answer_call[2])
    assert "original-task-sentinel" in restored_context
    assert "tool-result-sentinel" in restored_context
    assert answer_call[3] is not None
    assert app.state.call_log[-1]["tool_planning"] == "router"


class RouterDeclineResponsesClient(ContextAwareResponsesClient):
    def _reply(self, prompt: str) -> str:
        if "You are a tool-use router" in prompt:
            return "NO_TOOL_NEEDED"
        return "clean-answer-sentinel"


@pytest.mark.parametrize("stream", [False, True])
def test_responses_router_no_tool_marker_is_never_user_visible(stream, tmp_path):
    _app_obj, client, key, made = _custom_studio_app(
        tmp_path, RouterDeclineResponsesClient
    )
    _app_obj.state.key_store.update(
        _app_obj.state.key_store.resolve(key).id, tool_planning_mode="router"
    )

    response = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "m365-copilot",
            "input": "What is 2+2?",
            "stream": stream,
            "tools": [RESPONSES_READ_TOOL],
        },
    )

    assert response.status_code == 200
    body = _responses_body(response, stream)
    assert "clean-answer-sentinel" in json.dumps(body)
    assert "NO_TOOL_NEEDED" not in json.dumps(body)
    router_call = next(
        call
        for client_obj in made
        for call in client_obj.calls
        if "You are a tool-use router" in call[1]
    )
    assert router_call[3] is None


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("endpoint", ["messages", "responses"])
def test_ready_studio_endpoint_reports_studio_header(
    endpoint, stream, tmp_path
):
    _app_obj, client, key, _made = _app(tmp_path)
    if endpoint == "messages":
        response = client.post(
            "/v1/messages",
            headers={"x-api-key": key},
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 256,
                "stream": stream,
                "messages": [{"role": "user", "content": "read /tmp/a.txt"}],
                "tools": [{
                    "name": "Read",
                    "description": "Read a file",
                    "input_schema": READ_TOOL["function"]["parameters"],
                }],
            },
        )
    else:
        response = client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "claude-sonnet-4-6",
                "input": "read /tmp/a.txt",
                "stream": stream,
                "tools": [RESPONSES_READ_TOOL],
            },
        )

    assert response.status_code == 200
    assert response.headers["X-M365-Tool-Calling"] == "studio"
    if stream:
        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers["X-Accel-Buffering"] == "no"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("endpoint", ["messages", "responses"])
def test_other_tool_endpoints_zero_output_studio_error_falls_back_router(
    endpoint, stream, tmp_path
):
    app, client, key, made = _app(tmp_path, fail_studio=True)
    if endpoint == "messages":
        response = client.post(
            "/v1/messages",
            headers={"x-api-key": key},
            json={
                "model": "m365-copilot",
                "max_tokens": 256,
                "stream": stream,
                "messages": [{"role": "user", "content": "read /tmp/a.txt"}],
                "tools": [{
                    "name": "Read",
                    "description": "Read a file",
                    "input_schema": READ_TOOL["function"]["parameters"],
                }],
            },
        )
    else:
        response = client.post(
            "/v1/responses",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "m365-copilot",
                "input": "read /tmp/a.txt",
                "stream": stream,
                "tools": [RESPONSES_READ_TOOL],
            },
        )

    assert response.status_code == 200
    assert response.headers["X-M365-Tool-Calling"] == (
        "studio" if stream else "router"
    )
    assert [item.studio_agent_id for item in made] == ["", AGENT_ID]
    assert made[0].calls
    assert "You are a tool-use router" in made[0].calls[0][0]
    record = app.state.call_log[-1]
    assert record["tool_planning"] == "router"
    assert record["studio_fallback"] == "upstream_error"


def test_non_studio_responses_keeps_legacy_header_absence(tmp_path):
    app, client, key, _made = _app(tmp_path)
    key_obj = app.state.key_store.resolve(key)
    app.state.key_store.update(key_obj.id, tool_planning_mode="native")

    response = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "claude-sonnet-4-6",
            "input": "read /tmp/a.txt",
            "tools": [RESPONSES_READ_TOOL],
        },
    )

    assert response.status_code == 200
    assert "X-M365-Tool-Calling" not in response.headers


def _chat_response_text(response, *, stream: bool, required: bool) -> str:
    if required and not stream:
        return response.json()["error"]["message"]
    if not stream:
        return response.json()["choices"][0]["message"]["content"]
    chunks = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    return "".join(
        str(choice.get("delta", {}).get("content") or "")
        for chunk in chunks
        for choice in chunk.get("choices", [])
    )


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("required", [False, True])
def test_ready_studio_no_tool_diagnostics_never_claim_router(
    required, stream, tmp_path
):
    _app_obj, client, key, _made = _app(
        tmp_path,
        studio_outputs=["plain Studio answer without a call"],
    )
    body = {
        "model": "m365-copilot",
        "messages": [{"role": "user", "content": "answer without reading"}],
        "stream": stream,
        "tools": [READ_TOOL],
    }
    if required:
        body["tool_choice"] = "required"

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=body,
    )

    assert response.status_code == 200
    assert response.headers.get("X-M365-Tool-Calling") == (
        "studio" if stream else "router"
    )
    assert "X-M365-Tool-Outcome" not in response.headers
    if stream:
        chunks = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        tool_calls = [
            call
            for chunk in chunks
            for choice in chunk.get("choices", [])
            for call in choice.get("delta", {}).get("tool_calls", [])
        ]
    else:
        tool_calls = response.json()["choices"][0]["message"].get("tool_calls", [])
    assert [call.get("function", {}).get("name") for call in tool_calls] == ["Read"]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("required", [False, True])
def test_studio_error_router_fallback_diagnostics_report_actual_planner(
    required, stream, tmp_path
):
    _app_obj, client, key, _made = _app(
        tmp_path,
        fail_studio=True,
        ordinary_outputs=["unreadable router decision", "plain router answer"],
    )
    body = {
        "model": "m365-copilot",
        "messages": [{"role": "user", "content": "read /tmp/a.txt"}],
        "stream": stream,
        "tools": [READ_TOOL],
    }
    if required:
        body["tool_choice"] = "required"

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=body,
    )

    assert response.status_code == (200 if stream or not required else 400)
    assert response.headers["X-M365-Tool-Calling"] == (
        "studio" if stream else "inline"
    )
    text = _chat_response_text(response, stream=stream, required=required)
    if required:
        assert "tool_choice=required" in text
    else:
        assert "plain router answer" in text
        assert "工具路由器" not in text
    assert "Studio Agent" not in text


def test_studio_route_uses_one_subject_verified_snapshot_during_identity_change(
    monkeypatch, tmp_path
):
    app, client, key, made = _app(tmp_path)
    key_obj = app.state.key_store.resolve(key)
    account = app.state.account_store.get(key_obj.account_id)
    original_token = account.token
    original_snapshot = app.state.account_store.studio_client_snapshot

    def snapshot_then_change_subject(account_id):
        snapshot = original_snapshot(account_id)
        app.state.account_store.update_token(
            account_id,
            _jwt(tid="tenant-b", oid="object-b"),
        )
        return snapshot

    monkeypatch.setattr(
        app.state.account_store,
        "studio_client_snapshot",
        snapshot_then_change_subject,
    )

    response = _chat(client, key)

    assert response.status_code == 200
    assert response.headers["X-M365-Tool-Calling"] == "studio"
    assert made[-1].token == original_token
    assert made[-1].studio_agent_id == AGENT_ID
    assert account.studio_agent_ready is False


@pytest.mark.parametrize("stream", [False, True])
def test_studio_error_fallback_resets_failed_studio_conversation(stream, tmp_path):
    app, client, key, _made = _app(
        tmp_path,
        fail_studio=True,
        reserve_studio_turn_before_failure=True,
    )
    response = client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {key}",
            "x-m365-session-id": "failed-studio",
        },
        json={
            "model": "m365-copilot",
            "messages": [{"role": "user", "content": "read /tmp/a.txt"}],
            "stream": stream,
            "tools": [READ_TOOL],
        },
    )

    assert response.status_code == 200
    key_obj = app.state.key_store.resolve(key)
    account = app.state.account_store.get(key_obj.account_id)
    namespace = _studio_session_namespace(AGENT_ID)
    session = app.state.session_store.get_existing(
        f"{key_obj.id}:{account.id}:{namespace}:header:failed-studio"
    )
    assert session is not None
    assert session.turn_count == 0
