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


class FailingRefreshScheduler:
    async def inject_cookies(self, account_id: str, cookies: list[dict]) -> tuple[int, int]:
        return 0, len(cookies)


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


def test_cookie_push_persists_cookies_for_media_proxy(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")
    cookies = [{"name": "MUID", "value": "cookie-value", "domain": ".officeapps.live.com", "path": "/"}]

    response = TestClient(app).post(
        "/user/account/cookies",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"username": "Microsoft User", "cookies": cookies},
    )

    assert response.status_code == 200
    updated_key = app.state.key_store.get(key.id)
    account = app.state.account_store.get(updated_key.account_id)
    assert account.cookies == cookies


def test_media_auth_push_persists_bearer_for_bound_account(tmp_path):
    app = make_test_app(tmp_path)
    account = app.state.account_store.add(name="Microsoft User", token="substrate-token", token_source="manual")
    key = app.state.key_store.add(name="Proxy User", account_id=account.id, username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/media-auth",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"authorization": "Bearer media-bearer-token", "host": "jp-prod.asyncgw.teams.microsoft.com"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "has_media_auth": True}
    account = app.state.account_store.get(account.id)
    assert account.media_auth_token == "media-bearer-token"
    assert account.media_auth_updated_at > 0


def test_designer_auth_push_persists_raw_token_for_bound_account(tmp_path):
    # designerapp sends the Authorization value WITHOUT a "Bearer " prefix (raw
    # JWE), so it must be stored verbatim for later verbatim replay.
    app = make_test_app(tmp_path)
    account = app.state.account_store.add(name="Microsoft User", token="substrate-token", token_source="manual")
    key = app.state.key_store.add(name="Proxy User", account_id=account.id, username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/designer-auth",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"authorization": "raw-designer-jwe-token", "host": "designerapp.officeapps.live.com"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "has_designer_auth": True}
    account = app.state.account_store.get(account.id)
    assert account.designer_auth_token == "raw-designer-jwe-token"
    assert account.designer_auth_updated_at > 0


def test_designer_auth_push_rejects_non_designer_host(tmp_path):
    app = make_test_app(tmp_path)
    account = app.state.account_store.add(name="Microsoft User", token="substrate-token", token_source="manual")
    key = app.state.key_store.add(name="Proxy User", account_id=account.id, username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/designer-auth",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"authorization": "raw-designer-jwe-token", "host": "evil.example.com"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Unsupported designer auth host"


def test_media_auth_push_requires_existing_bound_account(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/media-auth",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"authorization": "Bearer media-bearer-token", "host": "jp-prod.asyncgw.teams.microsoft.com"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "No bound account"


def test_cookie_push_stores_cookies_even_when_chromium_injection_is_incomplete(tmp_path):
    app = make_test_app(tmp_path)
    app.state.refresh_scheduler = FailingRefreshScheduler()
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")
    cookies = [{"name": "MUID", "value": "cookie-value", "domain": ".officeapps.live.com", "path": "/"}]

    response = TestClient(app).post(
        "/user/account/cookies",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"username": "Microsoft User", "cookies": cookies},
    )

    assert response.status_code == 200
    assert response.json()["warning"] == "Cookie saved, but Chromium injection incomplete: 0/1"
    updated_key = app.state.key_store.get(key.id)
    account = app.state.account_store.get(updated_key.account_id)
    assert account.cookies == cookies
    assert account.cookie_valid is False


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

