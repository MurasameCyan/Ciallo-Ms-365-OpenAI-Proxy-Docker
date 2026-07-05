from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


class FakeRefreshScheduler:
    def __init__(self, account_store):
        self.account_store = account_store

    async def inject_cookies(self, account_id: str, cookies: list[dict]) -> tuple[int, int]:
        self.account_store.set_cookie_status(account_id, True)
        return len(cookies), len(cookies)


def make_test_app(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    app.state.refresh_scheduler = FakeRefreshScheduler(app.state.account_store)
    return app


def test_cookie_push_uses_microsoft_username_when_creating_account(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/cookies",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "username": "Microsoft User",
            "cookies": [{"name": "x", "value": "y", "domain": ".microsoft.com"}],
        },
    )

    assert response.status_code == 200
    updated_key = app.state.key_store.get(key.id)
    account = app.state.account_store.get(updated_key.account_id)
    assert account.name == "Microsoft User"


def test_cookie_push_renames_existing_account_to_microsoft_username(tmp_path):
    app = make_test_app(tmp_path)
    account = app.state.account_store.add(name="Proxy User", token="", token_source="cdp")
    key = app.state.key_store.add(name="Proxy User", account_id=account.id, username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/cookies",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "username": "Microsoft User",
            "cookies": [{"name": "x", "value": "y", "domain": ".microsoft.com"}],
        },
    )

    assert response.status_code == 200
    account = app.state.account_store.get(account.id)
    assert account.name == "Microsoft User"
