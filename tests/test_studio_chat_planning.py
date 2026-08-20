from __future__ import annotations

import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.models import OpenAIChatRequest, OpenAIMessage
from m365_copilot_openai_proxy.session_helpers import _persistent_session
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotError
from m365_copilot_openai_proxy.tone_options import router_applies, tool_planning_mode


AGENT_ID = "title.bot.gpt.default"
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


def test_ready_m365_tools_chat_uses_bound_studio_client(tmp_path):
    app, client, key, made = _app(tmp_path)

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


def test_ready_m365_stream_uses_studio_and_reports_actual_header(tmp_path):
    app, client, key, made = _app(tmp_path)

    response = _chat(client, key, stream=True)

    assert response.status_code == 200
    assert response.headers["X-M365-Tool-Calling"] == "studio"
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


def test_stream_zero_output_studio_error_reports_router_after_fallback(tmp_path):
    app, client, key, made = _app(tmp_path, fail_studio=True)

    response = _chat(client, key, stream=True)

    assert response.status_code == 200
    assert response.headers["X-M365-Tool-Calling"] == "router"
    assert len(made[0].calls) == 1
    assert app.state.call_log[-1]["studio_fallback"] == "upstream_error"
    persisted = json.loads(app.state.call_log_path.read_text(encoding="utf-8"))[-1]
    assert persisted["tool_planning"] == "router"
    assert persisted["studio_fallback"] == "upstream_error"


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
def test_unavailable_studio_chat_uses_router(provider, ready, reason, tmp_path):
    app, client, key, made = _app(tmp_path, provider=provider, ready=ready)

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
def test_other_tool_endpoints_explicitly_route_studio_mode(
    endpoint, headers, body, tmp_path
):
    app, client, key, made = _app(tmp_path)

    response = client.post(
        endpoint,
        json=body,
        headers={name: value.format(key=key) for name, value in headers.items()},
    )

    assert response.status_code == 200
    assert not [item for item in made if item.studio_agent_id]
    assert made[0].calls
    assert "You are a tool-use router" in made[0].calls[0][0]
    assert made[0].calls[0][1] is None
    record = app.state.call_log[-1]
    assert record["tool_planning"] == "router"
    assert record["studio_fallback"] == "unsupported_endpoint"


def test_responses_stream_studio_mode_uses_router_without_a_session(tmp_path):
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
    assert not [item for item in made if item.studio_agent_id]
    assert "You are a tool-use router" in made[0].calls[0][0]
    assert made[0].calls[0][1] is None
    record = app.state.call_log[-1]
    assert record["tool_planning"] == "router"
    assert record["studio_fallback"] == "unsupported_endpoint"


@pytest.mark.parametrize("stream", [False, True])
def test_responses_router_tool_continuation_restores_original_task_context(
    stream, tmp_path
):
    app, client, key, made = _custom_studio_app(
        tmp_path, ContextAwareResponsesClient
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
    continuation_client = made[-1]
    router_call = next(
        call for call in continuation_client.calls
        if "You are a tool-use router" in call[1]
    )
    assert router_call[3] is None
    assert "original-task-sentinel" in router_call[1]
    assert "tool-result-sentinel" in router_call[1]
    answer_call = next(
        call for call in continuation_client.calls
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
        call for call in made[-1].calls if "You are a tool-use router" in call[1]
    )
    assert router_call[3] is None


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("endpoint", ["messages", "responses"])
def test_unsupported_studio_endpoint_reports_actual_router_header(
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
    assert response.headers["X-M365-Tool-Calling"] == "router"


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

    assert response.status_code == (200 if stream or not required else 400)
    assert response.headers.get("X-M365-Tool-Calling") == "studio"
    assert response.headers.get("X-M365-Tool-Outcome") == (
        "required_no_call" if required and not stream else None
    )
    text = _chat_response_text(response, stream=stream, required=required)
    assert "Studio Agent" in text
    assert "工具路由器" not in text
    assert "Router" not in text


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
    assert response.headers["X-M365-Tool-Calling"] == "router"
    text = _chat_response_text(response, stream=stream, required=required)
    assert "工具路由器" in text
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
    session = app.state.session_store.get_existing(
        f"{key_obj.id}:{account.id}:studio:header:failed-studio"
    )
    assert session is not None
    assert session.turn_count == 0
