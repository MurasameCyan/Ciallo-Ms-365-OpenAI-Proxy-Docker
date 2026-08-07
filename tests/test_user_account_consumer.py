from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


class ExplodingRefreshScheduler:
    """Every consumer path must avoid the scheduler entirely; if the endpoint
    ever calls inject_cookies/ensure_fresh on a consumer push, these blow up."""

    async def inject_cookies(self, account_id: str, cookies: list[dict]) -> tuple[int, int]:
        raise AssertionError("consumer push must not inject cookies into Chromium")

    async def ensure_fresh(self, account_id: str, force: bool = False) -> bool:
        raise AssertionError("consumer push must not trigger a substrate refresh")


def make_test_app(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    app.state.refresh_scheduler = ExplodingRefreshScheduler()
    return app


TOKEN = "consumer-chatai-token-" + "x" * 30
COOKIES = [{"name": "_C_Auth", "value": "abc", "domain": ".copilot.microsoft.com"}]


def test_consumer_push_creates_account_flips_provider_and_binds_key(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={
            "username": "Personal User",
            "cookies": COOKIES,
            "access_token": TOKEN,
            "identity_type": "MSA",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "consumer", "cookies": 1}
    updated_key = app.state.key_store.get(key.id)
    account = app.state.account_store.get(updated_key.account_id)
    assert account.provider == "consumer"
    assert account.consumer_token == TOKEN
    assert account.consumer_identity_type == "MSA"
    assert account.cookies == COOKIES
    assert account.cookie_valid is True
    assert account.name == "Personal User"


def test_consumer_push_rejects_short_token(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"cookies": COOKIES, "access_token": "short"},
    )

    assert response.status_code == 400
    assert "token" in response.json()["error"]["message"].lower()


def test_consumer_push_rejects_empty_cookie_list(tmp_path):
    app = make_test_app(tmp_path)
    key = app.state.key_store.add(name="Proxy User", username="proxyuser", password="password1")

    response = TestClient(app).post(
        "/user/account/consumer",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"cookies": [], "access_token": TOKEN},
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "No cookies provided"


def test_consumer_account_excluded_from_refresh_scheduler(tmp_path):
    """ensure_fresh is the single entry point every refresh path shares; on a
    consumer account it must short-circuit rather than touch the M365 machinery,
    reporting usable iff a consumer token is stored."""
    from m365_copilot_openai_proxy.refresh_scheduler import RefreshScheduler

    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    store = app.state.account_store
    account = store.add(name="Personal User")
    store.set_consumer_auth(account.id, COOKIES, TOKEN, "MSA")

    scheduler = RefreshScheduler(store, tmp_path)
    assert asyncio.run(scheduler.ensure_fresh(account.id, force=True)) is True

    # A consumer account with no token is unusable, still without touching M365.
    store.set_consumer_auth(account.id, COOKIES, "", "")
    assert asyncio.run(scheduler.ensure_fresh(account.id, force=True)) is False


def test_consumer_provider_surfaces_in_public_serializer_without_leaking_token(tmp_path):
    from m365_copilot_openai_proxy.account_serializers import user_account_public

    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    store = app.state.account_store
    account = store.add(name="Personal User")
    store.set_consumer_auth(account.id, COOKIES, TOKEN, "MSA")

    public = user_account_public(store.get(account.id))
    assert public["provider"] == "consumer"
    assert public["has_consumer_token"] is True
    assert TOKEN not in str(public)


def test_consumer_token_is_encrypted_at_rest_and_survives_reload(tmp_path):
    """The ChatAI token is a live credential, so it must be in SENSITIVE_FIELDS:
    absent from the plaintext of accounts.json, yet identical after a reload."""
    from m365_copilot_openai_proxy.account_store import AccountStore

    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    account = store.add(name="Personal User")
    store.set_consumer_auth(account.id, COOKIES, TOKEN, "MSA")

    on_disk = persist.read_text(encoding="utf-8")
    # Only meaningful when cryptography is installed; degrade like account_crypto.
    from m365_copilot_openai_proxy.account_crypto import _HAVE_CRYPTO

    if _HAVE_CRYPTO:
        assert TOKEN not in on_disk

    reloaded = AccountStore(persist_path=persist).get(account.id)
    assert reloaded.provider == "consumer"
    assert reloaded.consumer_token == TOKEN
    assert reloaded.consumer_identity_type == "MSA"
