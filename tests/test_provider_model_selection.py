from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy import (
    routes_api_chat,
    routes_api_messages,
    routes_api_responses,
)
from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.consumer_client import ConsumerCopilotError
from m365_copilot_openai_proxy.session_helpers import _encode_responses_session_id


_ROLLOUT_HINT = "该实验 mode 可能受账户、地区或 Microsoft rollout 限制"


class _FakeConsumerClient:
    def __init__(self):
        self.mode = "smart"
        self.fail = None
        self.calls = 0
        self.prompts = []
        self.images = []

    async def chat_stream(self, prompt, conversation_id="", images=None):
        self.calls += 1
        self.prompts.append(prompt)
        self.images.append(images)
        if self.fail:
            raise self.fail
        yield "ok"


class _FakeM365Client:
    def __init__(self, tone="Magic"):
        self._tone = tone or "Magic"
        self.calls = []

    async def chat(self, prompt, additional_context, session=None, images=None):
        self.calls.append((prompt, additional_context))
        return "ok"


_ROUTE_CASES = [
    (
        "/v1/chat/completions",
        {
            "model": "deep-alias",
            "messages": [{"role": "user", "content": "ping"}],
        },
    ),
    (
        "/v1/messages",
        {
            "model": "deep-alias",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "ping"}],
        },
    ),
    (
        "/v1/responses",
        {"model": "deep-alias", "input": "ping"},
    ),
]


@pytest.fixture
def provider_app(tmp_path):
    made_m365 = []

    def m365_factory(tone=None, **kwargs):
        client = _FakeM365Client(tone)
        made_m365.append(client)
        return client

    app = create_app(
        Settings(
            TOKEN_DIR=str(tmp_path),
            API_KEY="admin-key",
            ADMIN_PASSWORD="admin-pass",
            M365_ACCESS_TOKEN="",
        ),
        copilot_client_factory=m365_factory,
    )
    consumer = app.state.account_store.add(name="Consumer")
    app.state.account_store.set_consumer_auth(
        consumer.id,
        cookies=[],
        access_token="consumer-token",
    )
    consumer_key = app.state.key_store.add(
        name="Consumer Key", account_id=consumer.id,
    )

    m365 = app.state.account_store.add(name="M365", token="m365-token")
    m365_key = app.state.key_store.add(name="M365 Key", account_id=m365.id)

    made_consumers = []

    def consumer_factory(**kwargs):
        client = _FakeConsumerClient()
        made_consumers.append(client)
        return client

    app.state.consumer_client_factory = consumer_factory
    return app, consumer_key, m365_key, made_consumers, made_m365


def _body_with_model(body: dict, model: str) -> dict:
    return {**body, "model": model}


def _body_with_history(endpoint: str, body: dict, history: str, prompt: str) -> dict:
    updated = dict(body)
    if endpoint == "/v1/responses":
        updated["input"] = [
            {"role": "user", "content": history},
            {"role": "assistant", "content": "ack"},
            {"role": "user", "content": prompt},
        ]
    else:
        updated["messages"] = [
            {"role": "user", "content": history},
            {"role": "assistant", "content": "ack"},
            {"role": "user", "content": prompt},
        ]
    return updated


@pytest.mark.parametrize("endpoint,body", _ROUTE_CASES)
def test_consumer_routes_cap_long_history_and_keep_current_prompt(
    provider_app, endpoint, body,
):
    app, consumer_key, _m365_key, made_consumers, made_m365 = provider_app
    app.state.settings.consumer_prompt_max_chars = 1000
    app.state.consumer_mode_options = [
        {"model": "deep-alias", "mode": "smart", "status": "stable"},
    ]
    history = "OLD_HISTORY_HEAD\n" + ("你" * 3000) + "\nOLD_HISTORY_TAIL"
    current = "CURRENT_USER_SENTINEL"

    response = TestClient(app).post(
        endpoint,
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json=_body_with_history(endpoint, body, history, current),
    )

    assert response.status_code == 200
    sent = made_consumers[-1].prompts[-1]
    assert len(sent) <= 1000
    assert sent.endswith(current)
    assert "OLD_HISTORY_HEAD" not in sent
    assert "OLD_HISTORY_TAIL" in sent
    assert made_m365 == []


# --- inbound images reach the consumer client -------------------------------
#
# End to end for the seam the bridge used to sever: the route translates the
# image, the adapter forwards it, and the consumer client is the one that
# uploads it (`/c/api/attachments`). Before 2026-09-04 the translator refused an
# image-only consumer turn with a 400 and the adapter dropped images from every
# other turn, so all three endpoints answered blind while Copilot's own web UI
# read pictures fine.

_PNG_DATA_URL = "data:image/png;base64,aGVsbG8="

_IMAGE_ROUTE_CASES = [
    (
        "/v1/chat/completions",
        {
            "model": "deep-alias",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this"},
                        {"type": "image_url", "image_url": {"url": _PNG_DATA_URL}},
                    ],
                }
            ],
        },
    ),
    (
        "/v1/messages",
        {
            "model": "deep-alias",
            "max_tokens": 64,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "aGVsbG8=",
                            },
                        },
                    ],
                }
            ],
        },
    ),
    (
        "/v1/responses",
        {
            "model": "deep-alias",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "what is this"},
                        {"type": "input_image", "image_url": {"url": _PNG_DATA_URL}},
                    ],
                }
            ],
        },
    ),
]


@pytest.mark.parametrize("endpoint,body", _IMAGE_ROUTE_CASES)
def test_consumer_routes_hand_inbound_images_to_the_client(
    provider_app, endpoint, body,
):
    app, consumer_key, _m365_key, made_consumers, _made_m365 = provider_app
    app.state.consumer_mode_options = [
        {"model": "deep-alias", "mode": "smart", "status": "stable"},
    ]

    response = TestClient(app).post(
        endpoint,
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json=body,
    )

    assert response.status_code == 200
    images = made_consumers[-1].images[-1]
    assert images and len(images) == 1
    assert images[0].base64 == "aGVsbG8="
    assert made_consumers[-1].prompts[-1].endswith("what is this")


@pytest.mark.parametrize("endpoint,body", _IMAGE_ROUTE_CASES)
def test_consumer_image_only_turn_is_answered_not_rejected(
    provider_app, endpoint, body,
):
    """The picture is the whole question. This used to be a 400 from the
    translator; upstream answers it (measured against the live account)."""
    app, consumer_key, _m365_key, made_consumers, _made_m365 = provider_app
    app.state.consumer_mode_options = [
        {"model": "deep-alias", "mode": "smart", "status": "stable"},
    ]
    stripped = dict(body)
    key = "input" if endpoint == "/v1/responses" else "messages"
    turn = dict(stripped[key][0])
    turn["content"] = [
        part
        for part in turn["content"]
        if part["type"] not in ("text", "input_text")
    ]
    stripped[key] = [turn]

    response = TestClient(app).post(
        endpoint,
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json=stripped,
    )

    assert response.status_code == 200
    assert len(made_consumers[-1].images[-1]) == 1


@pytest.mark.parametrize("endpoint,body", _ROUTE_CASES)
def test_m365_routes_do_not_apply_consumer_history_limit(provider_app, endpoint, body):
    app, _consumer_key, m365_key, made_consumers, made_m365 = provider_app
    app.state.settings.consumer_prompt_max_chars = 1000
    app.state.tone_options = [{"value": "Magic", "label": "自动"}]
    history = "OLD_HISTORY_HEAD\n" + ("你" * 3000) + "\nOLD_HISTORY_TAIL"
    current = "CURRENT_USER_SENTINEL"

    response = TestClient(app).post(
        endpoint,
        headers={"Authorization": f"Bearer {m365_key.key}"},
        json=_body_with_model(
            _body_with_history(endpoint, body, history, current),
            "Magic",
        ),
    )

    assert response.status_code == 200
    prompt, context = made_m365[-1].calls[-1]
    assert prompt == current
    joined = "\n\n".join(context)
    assert history in joined
    assert len(joined) + len(prompt) > 1000
    assert "omitted for Consumer Copilot prompt budget" not in joined
    assert made_consumers == []


@pytest.mark.parametrize(
    "endpoint,tool",
    [
        (
            "/v1/chat/completions",
            {
                "type": "function",
                "function": {
                    "name": "Read",
                    "parameters": {
                        "type": "object",
                        "properties": {"file_path": {"type": "string"}},
                        "required": ["file_path"],
                    },
                },
            },
        ),
        (
            "/v1/messages",
            {
                "name": "Read",
                "input_schema": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            },
        ),
    ],
)
def test_consumer_tool_stream_rejects_mandatory_content_before_upstream_call(
    provider_app, endpoint, tool,
):
    app, consumer_key, _m365_key, made_consumers, _made_m365 = provider_app
    app.state.settings.consumer_prompt_max_chars = 320
    app.state.consumer_mode_options = [
        {"model": "deep-alias", "mode": "smart", "status": "stable"},
    ]
    body = {
        "model": "deep-alias",
        "stream": True,
        "messages": [{"role": "user", "content": "CURRENT_" + ("x" * 100)}],
        "tools": [tool],
    }
    if endpoint == "/v1/messages":
        body["max_tokens"] = 64

    response = TestClient(app).post(
        endpoint,
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json=body,
    )

    assert response.status_code == 400
    assert "required tool signatures and current user prompt" in response.text
    assert made_consumers[-1].calls == 0


@pytest.mark.parametrize("endpoint,body", _ROUTE_CASES)
def test_consumer_routes_apply_live_model_mode_without_m365_session(
    provider_app, monkeypatch, endpoint, body,
):
    app, consumer_key, _m365_key, made_consumers, _made_m365 = provider_app
    app.state.consumer_mode_options = [
        {
            "model": "deep-alias",
            "mode": "ReASoning",
            "status": "experimental",
        },
    ]

    def unexpected_session(*args, **kwargs):
        raise AssertionError("Consumer must not create an M365 persistent session")

    for module in (routes_api_chat, routes_api_messages, routes_api_responses):
        monkeypatch.setattr(module, "_persistent_session", unexpected_session)

    response = TestClient(app).post(
        endpoint,
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json=_body_with_model(body, "  DEEP-ALIAS  "),
    )

    assert response.status_code == 200
    assert made_consumers[-1].mode == "ReASoning"
    assert not hasattr(made_consumers[-1], "_tone")
    assert app.state.call_log[-1]["tone"] == "ReASoning"


@pytest.mark.parametrize("endpoint,body", _ROUTE_CASES)
@pytest.mark.parametrize("status", ["stable", "experimental"])
def test_consumer_non_stream_errors_preserve_upstream_message_and_status_hint(
    provider_app, endpoint, body, status,
):
    app, consumer_key, _m365_key, made_consumers, _made_m365 = provider_app
    app.state.consumer_mode_options = [
        {"model": "deep-alias", "mode": "reasoning", "status": status},
    ]

    def failing_factory(**kwargs):
        client = _FakeConsumerClient()
        client.fail = ConsumerCopilotError("upstream mode error E_MODE")
        made_consumers.append(client)
        return client

    app.state.consumer_client_factory = failing_factory
    response = TestClient(app).post(
        endpoint,
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json=body,
    )

    assert response.status_code == 502
    message = response.json()["error"]["message"]
    assert "upstream mode error E_MODE" in message
    assert (_ROLLOUT_HINT in message) is (status == "experimental")
    assert made_consumers[-1].mode == "reasoning"
    assert made_consumers[-1].calls == 1


@pytest.mark.parametrize("endpoint,body", _ROUTE_CASES)
def test_consumer_stream_errors_keep_experimental_hint_in_route_envelopes(
    provider_app, endpoint, body,
):
    app, consumer_key, _m365_key, made_consumers, _made_m365 = provider_app
    app.state.consumer_mode_options = [
        {
            "model": "deep-alias",
            "mode": "reasoning",
            "status": "experimental",
        },
    ]

    def failing_factory(**kwargs):
        client = _FakeConsumerClient()
        client.fail = ConsumerCopilotError("stream mode error E_STREAM")
        made_consumers.append(client)
        return client

    app.state.consumer_client_factory = failing_factory
    response = TestClient(app).post(
        endpoint,
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json={**body, "stream": True},
    )

    assert response.status_code == 200
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    decoded_payloads = json.dumps(payloads, ensure_ascii=False)
    assert "stream mode error E_STREAM" in decoded_payloads
    assert _ROLLOUT_HINT in decoded_payloads
    assert made_consumers[-1].mode == "reasoning"
    assert made_consumers[-1].calls == 1
    if endpoint == "/v1/responses":
        assert '"type": "response.failed"' in response.text
    elif endpoint == "/v1/messages":
        assert "event: content_block_delta" in response.text
        assert "event: message_stop" in response.text
        assert "event: error" not in response.text
    else:
        assert "data: [DONE]" in response.text


def test_consumer_chat_tool_stream_preserves_experimental_upstream_error(
    provider_app,
):
    app, consumer_key, _m365_key, made_consumers, _made_m365 = provider_app
    app.state.consumer_mode_options = [
        {
            "model": "deep-alias",
            "mode": "reasoning",
            "status": "experimental",
        },
    ]

    def failing_factory(**kwargs):
        client = _FakeConsumerClient()
        client.fail = ConsumerCopilotError("tool stream mode error E_TOOL_STREAM")
        made_consumers.append(client)
        return client

    app.state.consumer_client_factory = failing_factory
    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json={
            "model": "deep-alias",
            "stream": True,
            "messages": [{"role": "user", "content": "ping"}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "noop",
                    "parameters": {"type": "object", "properties": {}},
                },
            }],
        },
    )

    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    decoded_payloads = json.dumps(payloads, ensure_ascii=False)
    assert response.status_code == 200
    assert "tool stream mode error E_TOOL_STREAM" in decoded_payloads
    assert _ROLLOUT_HINT in decoded_payloads
    assert response.text.endswith("data: [DONE]\n\n")
    assert made_consumers[-1].mode == "reasoning"
    assert made_consumers[-1].calls == 1


def test_consumer_anthropic_tool_stream_error_is_visible_and_logged(provider_app):
    app, consumer_key, _m365_key, made_consumers, _made_m365 = provider_app
    app.state.consumer_mode_options = [
        {"model": "deep-alias", "mode": "reasoning", "status": "experimental"},
    ]

    def failing_factory(**kwargs):
        client = _FakeConsumerClient()
        client.fail = ConsumerCopilotError("tool stream mode error E_ANTHROPIC_TOOL")
        made_consumers.append(client)
        return client

    app.state.consumer_client_factory = failing_factory
    response = TestClient(app).post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json={
            "model": "deep-alias",
            "max_tokens": 64,
            "stream": True,
            "messages": [{"role": "user", "content": "ping"}],
            "tools": [{
                "name": "Write",
                "description": "Write a file",
                "input_schema": {"type": "object", "properties": {}},
            }],
        },
    )

    assert response.status_code == 200
    assert "event: content_block_delta" in response.text
    assert "event: message_stop" in response.text
    assert "event: error" not in response.text
    assert "tool stream mode error E_ANTHROPIC_TOOL" in response.text
    assert app.state.call_log[-1]["tools"] == ["Write"]
    assert "tool stream mode error E_ANTHROPIC_TOOL" in app.state.call_log[-1]["response_text"]
    assert made_consumers[-1].calls == 1


@pytest.mark.parametrize("endpoint,body", _ROUTE_CASES)
def test_unknown_consumer_model_is_rejected_before_client_creation(
    provider_app, endpoint, body,
):
    app, consumer_key, _m365_key, made_consumers, _made_m365 = provider_app
    app.state.consumer_mode_options = [
        {"model": "live-smart", "mode": "smart", "status": "stable"},
        {"model": "live-deep", "mode": "reasoning", "status": "experimental"},
    ]

    response = TestClient(app).post(
        endpoint,
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json=_body_with_model(body, "Unknown-Consumer"),
    )

    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert "Unknown-Consumer" in message
    assert "live-smart" in message
    assert "live-deep" in message
    assert made_consumers == []


def test_provider_is_selected_from_bound_account_not_model_name(provider_app):
    app, consumer_key, m365_key, made_consumers, made_m365 = provider_app
    client = TestClient(app)
    body = {
        "model": "Gpt_5_6_Reasoning",
        "messages": [{"role": "user", "content": "ping"}],
    }

    consumer_response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json=body,
    )
    m365_response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {m365_key.key}"},
        json={**body, "model": "copilot-reasoning"},
    )
    global_response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer admin-key"},
        json={**body, "model": "copilot-reasoning"},
    )

    assert consumer_response.status_code == 400
    assert made_consumers == []
    assert m365_response.status_code == 200
    assert global_response.status_code == 200
    assert [consumer._tone for consumer in made_m365[-2:]] == ["Magic", "Magic"]


def test_m365_responses_allows_incremental_tool_output_for_proxy_response_id(
    provider_app,
):
    app, _consumer_key, m365_key, _made_consumers, made_m365 = provider_app
    # Keyed requests include the currently bound account in their tenant
    # prefix.  Build the fixture's issued response id from the same scope so
    # the test exercises continuation authorization rather than an orphaned
    # legacy key.
    session_key = (
        f"{m365_key.id}:{m365_key.account_id}:auto:responses-history"
    )
    session = app.state.session_store.get(session_key)
    previous_response_id = _encode_responses_session_id(
        session_key,
        app.state.media_proxy_secret,
        {"call_from_server_history"},
    )
    session.reserve_turn()
    session.record_response(
        previous_response_id,
        ["call_from_server_history"],
    )

    response = TestClient(app).post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {m365_key.key}"},
        json={
            "model": "Magic",
            "previous_response_id": previous_response_id,
            "input": [{
                "type": "function_call_output",
                "call_id": "call_from_server_history",
                "output": "real result",
            }],
        },
    )

    assert response.status_code == 200
    assert made_m365[-1].calls


@pytest.mark.parametrize("provider", ["m365", "consumer"])
def test_responses_rejects_orphan_tool_output_without_m365_server_history(
    provider_app, provider,
):
    app, consumer_key, m365_key, made_consumers, made_m365 = provider_app
    key = m365_key if provider == "m365" else consumer_key
    model = "Magic" if provider == "m365" else "deep-alias"
    app.state.consumer_mode_options = [
        {"model": "deep-alias", "mode": "reasoning", "status": "stable"},
    ]

    response = TestClient(app).post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "model": model,
            "previous_response_id": (
                _encode_responses_session_id("missing-history")
                if provider == "m365"
                else _encode_responses_session_id("consumer-history")
            ),
            "input": [{
                "type": "function_call_output",
                "call_id": "call_missing",
                "output": "real result",
            }],
        },
    )

    assert response.status_code == 400
    expected = (
        "Invalid or expired Responses previous_response_id"
        if provider == "m365"
        else "matching function_call"
    )
    assert expected in response.text
    assert all(consumer.calls == 0 for consumer in made_consumers)
    assert all(client.calls == [] for client in made_m365)


@pytest.mark.parametrize("endpoint,body", _ROUTE_CASES)
def test_m365_routes_still_apply_model_as_tone_and_session(
    provider_app, monkeypatch, endpoint, body,
):
    app, _consumer_key, m365_key, _made_consumers, made_m365 = provider_app
    app.state.tone_options = [
        {"value": "Magic", "label": "自动"},
        {"value": "Gpt_5_6_Reasoning", "label": "GPT_5.6_推理"},
    ]
    session_calls = []

    def session_spy(*args, **kwargs):
        session_calls.append((args, kwargs))
        return None

    for module in (routes_api_chat, routes_api_messages, routes_api_responses):
        monkeypatch.setattr(module, "_persistent_session", session_spy)

    response = TestClient(app).post(
        endpoint,
        headers={"Authorization": f"Bearer {m365_key.key}"},
        json=_body_with_model(body, "GPT_5.6_推理"),
    )

    assert response.status_code == 200
    assert made_m365[-1]._tone == "Gpt_5_6_Reasoning"
    assert len(session_calls) == 1
    assert not hasattr(made_m365[-1], "mode")


def test_models_list_is_provider_specific_and_live(provider_app):
    app, consumer_key, m365_key, _made_consumers, _made_m365 = provider_app
    app.state.consumer_mode_options = [
        {"model": "custom-smart", "mode": "smart", "status": "stable"},
        {"model": "deep-alias", "mode": "reasoning", "status": "experimental"},
        {"model": "deep-alias-2", "mode": "reasoning", "status": "experimental"},
    ]
    app.state.tone_options = [{"value": "Magic", "label": "自动"}]
    client = TestClient(app)

    consumer_models = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {consumer_key.key}"},
    ).json()["data"]
    m365_models = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {m365_key.key}"},
    ).json()["data"]
    global_models = client.get(
        "/v1/models",
        headers={"Authorization": "Bearer admin-key"},
    ).json()["data"]

    assert [model["id"] for model in consumer_models] == [
        "custom-smart", "deep-alias", "deep-alias-2",
    ]
    assert all(model["owned_by"] == "microsoft-copilot" for model in consumer_models)
    assert all("status" not in model for model in consumer_models)
    assert all(
        "-持续" not in model["id"] and ":persist" not in model["id"]
        for model in consumer_models
    )
    assert [model["id"] for model in m365_models] == ["自动", "自动-持续"]
    assert [model["id"] for model in global_models] == ["自动", "自动-持续"]


def test_default_consumer_models_include_tested_catalog(provider_app):
    app, consumer_key, _m365_key, _made_consumers, _made_m365 = provider_app

    models = TestClient(app).get(
        "/v1/models",
        headers={"Authorization": f"Bearer {consumer_key.key}"},
    ).json()["data"]

    assert [model["id"] for model in models] == [
        "copilot-reasoning",
        "copilot-thinking",
        "copilot-research",
        "copilot-coco",
        "copilot-search",
        "copilot",
        "copilot-smart",
        "copilot-chat",
        "copilot-study",
    ]


def test_model_alias_only_changes_response_display(provider_app):
    app, consumer_key, _m365_key, made_consumers, _made_m365 = provider_app
    app.state.model_alias = "display-only"
    app.state.consumer_mode_options = [
        {"model": "deep-alias", "mode": "reasoning", "status": "experimental"},
    ]
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {consumer_key.key}"},
        json={
            "model": "deep-alias",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )
    models = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {consumer_key.key}"},
    ).json()["data"]

    assert response.status_code == 200
    assert response.json()["model"] == "display-only"
    assert made_consumers[-1].mode == "reasoning"
    assert [model["id"] for model in models] == ["deep-alias"]


def test_substrate_payload_keeps_using_tone():
    from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotClient

    client = object.__new__(SubstrateCopilotClient)
    client._tone = "Gpt_5_6_Reasoning"
    client._extra_tool_prompt = ""
    client._time_zone = "Asia/Shanghai"

    payload = json.loads(
        client._chat_invoke(
            "ping",
            "conversation-id",
            "session-id",
            "request-id",
            True,
        ).rstrip("\x1e")
    )

    argument = payload["arguments"][0]
    assert argument["tone"] == "Gpt_5_6_Reasoning"
    assert "mode" not in argument
    assert "toneId" not in argument
