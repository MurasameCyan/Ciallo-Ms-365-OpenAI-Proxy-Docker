"""POST /user/account/proxy contract.

The endpoint writes to the bound account, so it must refuse when the key has no
binding: silently succeeding would tell the user their egress changed when
nothing was stored.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))


@pytest.fixture
def user_client(app, tmp_path):
    """TestClient with a key bound to an account."""
    account = app.state.account_store.add(name="Test User")
    key = app.state.key_store.add(name="Test Key", account_id=account.id)
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {key.key}"
    return client


@pytest.fixture
def bound_account(app, user_client):
    """Callable that returns the current bound account."""
    def _get_account():
        # Extract the key from the client's Authorization header
        auth_header = user_client.headers["Authorization"]
        bearer_token = auth_header.split(" ", 1)[1]
        # Find the key by token
        for key in app.state.key_store.list():
            if key.key == bearer_token:
                return app.state.account_store.get(key.account_id)
        return None
    return _get_account


@pytest.fixture
def user_client_unbound(app):
    """TestClient with a key that has no account binding."""
    key = app.state.key_store.add(name="Unbound Key")
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {key.key}"
    return client


def test_sets_proxy_on_bound_account(user_client, bound_account):
    r = user_client.post("/user/account/proxy", json={"proxy_url": "socks5h://127.0.0.1:1080"})
    assert r.status_code == 200
    assert r.json()["proxy_url"] == "socks5h://127.0.0.1:1080"
    assert bound_account().proxy_url == "socks5h://127.0.0.1:1080"


def test_clears_proxy_with_empty_string(user_client, bound_account):
    user_client.post("/user/account/proxy", json={"proxy_url": "socks5h://127.0.0.1:1080"})
    r = user_client.post("/user/account/proxy", json={"proxy_url": ""})
    assert r.status_code == 200
    assert r.json()["proxy_url"] == ""
    assert bound_account().proxy_url == ""


def test_rejects_unusable_url_without_clearing(user_client, bound_account):
    user_client.post("/user/account/proxy", json={"proxy_url": "socks5h://127.0.0.1:1080"})
    r = user_client.post("/user/account/proxy", json={"proxy_url": "not-a-proxy"})
    assert r.status_code == 400
    assert bound_account().proxy_url == "socks5h://127.0.0.1:1080"


def test_rejects_when_no_account_bound(user_client_unbound):
    r = user_client_unbound.post("/user/account/proxy", json={"proxy_url": "http://h:1080"})
    assert r.status_code == 400


def test_me_reports_proxy_url(user_client, bound_account):
    user_client.post("/user/account/proxy", json={"proxy_url": "socks5h://127.0.0.1:1080"})
    account = user_client.get("/user/me").json()["account"]
    assert account["proxy_url"] == "socks5h://127.0.0.1:1080"
