from __future__ import annotations

import json

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_api import register_api_routes


def test_v1_api_routes_are_registered_by_api_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_api_routes)
    assert "/v1/models" in paths
    assert "/v1/chat/completions" in paths
    assert "/v1/responses" in paths
    assert "/v1/messages" in paths
    assert "/v1/images/generations" in paths


def test_chat_completions_uses_reloaded_bound_account_token_without_global_token(tmp_path):
    first_app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass", M365_ACCESS_TOKEN=""))
    account = first_app.state.account_store.add(name="Bound Account", token="account-token", token_source="manual")
    first_app.state.account_store.set_cookies(account.id, [{"name": "MUID", "value": "cookie-value"}])
    key = first_app.state.key_store.add(name="Bound Key", account_id=account.id)

    seen_tokens = []

    class FakeCopilotClient:
        async def chat(self, prompt, additional_context, session=None, images=None):
            return "ok"

    def factory(token=None, **kwargs):
        seen_tokens.append(token)
        if token != "account-token":
            raise AssertionError(f"expected bound account token, got {token!r}")
        return FakeCopilotClient()

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass", M365_ACCESS_TOKEN=""),
        copilot_client_factory=factory,
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "m365-copilot", "messages": [{"role": "user", "content": "ping"}]},
    )

    assert response.status_code == 200
    assert seen_tokens == ["account-token"]
    assert response.json()["choices"][0]["message"]["content"] == "ok"


def test_chat_stream_does_not_emit_duplicate_media_citation_fallback_after_proxy_rewrite(tmp_path):
    first_app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass", M365_ACCESS_TOKEN=""))
    account = first_app.state.account_store.add(name="Stream Account", token="account-token", token_source="manual")
    key = first_app.state.key_store.add(name="Stream Key", account_id=account.id)
    media_url = "https://kr-prod.asyncgw.teams.microsoft.com/v1/objects/0-ea-d2/views/original/flowing_water.wav"

    class FakeCopilotClient:
        async def chat_stream(self, prompt, additional_context, session=None, images=None):
            yield f"已生成流水声（WAV 格式）：\n\n🎧 `{media_url}` \n\n这是一个约 12 秒的潺潺流水音效。"
            yield "已生成流水声（WAV 格式）：\n\n🎧 [流水声](\ue200cite\ue202turn1file1\ue201)\n\n这是一个约 12 秒的潺潺流水音效。"

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass", M365_ACCESS_TOKEN=""),
        copilot_client_factory=lambda **kwargs: FakeCopilotClient(),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"model": "m365-copilot", "stream": True, "messages": [{"role": "user", "content": "流水声"}]},
    )

    assert response.status_code == 200
    emitted = ""
    for block in response.text.split("\n\n"):
        if not block.startswith("data: ") or block == "data: [DONE]":
            continue
        payload = json.loads(block.removeprefix("data: "))
        emitted += payload.get("choices", [{}])[0].get("delta", {}).get("content", "")
    assert emitted.count("已生成流水声（WAV 格式）") == 1
    assert "/v1/m365-media?" in emitted


class _CountingCopilotClient:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, prompt, additional_context, session=None, images=None):
        self.calls += 1
        return "unexpected upstream response"


def _orphan_test_client(tmp_path):
    upstream = _CountingCopilotClient()
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **_kwargs: upstream,
    )
    return TestClient(app), upstream


def test_chat_rejects_an_orphan_tool_result_before_calling_upstream(tmp_path):
    client, upstream = _orphan_test_client(tmp_path)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer k"},
        json={
            "model": "m365-copilot",
            "messages": [
                {"role": "tool", "tool_call_id": "ghost_chat", "content": "42"}
            ],
        },
    )

    assert response.status_code == 400
    assert "ghost_chat" in response.json()["error"]["message"]
    assert upstream.calls == 0


def test_messages_rejects_an_orphan_tool_result_before_calling_upstream(tmp_path):
    client, upstream = _orphan_test_client(tmp_path)

    response = client.post(
        "/v1/messages",
        headers={"x-api-key": "k", "anthropic-version": "2023-06-01"},
        json={
            "model": "m365-copilot",
            "max_tokens": 64,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "ghost_messages",
                            "content": "42",
                        }
                    ],
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "ghost_messages" in response.json()["error"]["message"]
    assert upstream.calls == 0
