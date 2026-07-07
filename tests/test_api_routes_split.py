from __future__ import annotations

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


def test_chat_completions_uses_reloaded_bound_account_token_without_global_token(tmp_path):
    first_app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key", ADMIN_PASSWORD="admin-pass", M365_ACCESS_TOKEN=""))
    account = first_app.state.account_store.add(name="Bound Account", token="account-token", token_source="manual")
    first_app.state.account_store.set_cookies(account.id, [{"name": "MUID", "value": "cookie-value"}])
    key = first_app.state.key_store.add(name="Bound Key", account_id=account.id)

    seen_tokens = []

    class FakeCopilotClient:
        async def chat(self, prompt, additional_context, session=None):
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
