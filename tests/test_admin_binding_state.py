from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


def make_admin_client(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    client = TestClient(app)
    response = client.post("/admin/login", json={"password": "admin-key"})
    assert response.status_code == 200
    return app, client


def test_admin_accounts_include_binding_state_without_ui_changes(tmp_path):
    app, client = make_admin_client(tmp_path)
    none_account = app.state.account_store.add(name="No Binding", token="", token_source="cdp")
    token_account = app.state.account_store.add(name="Token Only", token="token-value", token_source="manual")
    cookie_account = app.state.account_store.add(name="Cookie Bound", token="", token_source="cdp")
    app.state.account_store.set_cookie_status(cookie_account.id, True)

    response = client.get("/admin/accounts")

    assert response.status_code == 200
    accounts = {account["id"]: account for account in response.json()["accounts"]}
    assert accounts[none_account.id]["binding_state"] == "none"
    assert accounts[token_account.id]["binding_state"] == "token_only"
    assert accounts[cookie_account.id]["binding_state"] == "cookie"
