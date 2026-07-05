from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


def make_test_app(tmp_path):
    return create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))


def get_user_me(app, api_key: str):
    response = TestClient(app).get("/user/me", headers={"Authorization": f"Bearer {api_key}"})
    assert response.status_code == 200
    return response.json()


def test_user_me_binding_state_is_none_without_account(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    data = get_user_me(app, key.key)

    assert data["binding_state"] == "none"
    assert data["account"] is None


def test_user_me_binding_state_is_token_only_without_valid_cookie(tmp_path):
    app = make_test_app(tmp_path)
    account = app.state.account_store.add(name="Microsoft User", token="token-value", token_source="manual")
    key = app.state.key_store.add(name="Proxy User", account_id=account.id, username="proxyuser", password="password1")

    data = get_user_me(app, key.key)

    assert data["binding_state"] == "token_only"
    assert data["account"]["binding_state"] == "token_only"


def test_user_me_binding_state_is_cookie_when_cookie_is_valid(tmp_path):
    app = make_test_app(tmp_path)
    account = app.state.account_store.add(name="Microsoft User", token="", token_source="cdp")
    app.state.account_store.set_cookie_status(account.id, True)
    key = app.state.key_store.add(name="Proxy User", account_id=account.id, username="proxyuser", password="password1")

    data = get_user_me(app, key.key)

    assert data["binding_state"] == "cookie"
    assert data["account"]["binding_state"] == "cookie"
