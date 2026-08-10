from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


def _client(tmp_path) -> TestClient:
    client = TestClient(
        create_app(
            Settings(
                TOKEN_DIR=str(tmp_path),
                API_KEY="api-key",
                ADMIN_PASSWORD="admin-pass",
            )
        )
    )
    assert client.post("/admin/login", json={"password": "admin-pass"}).status_code == 200
    return client


def _consumer(client: TestClient) -> str:
    store = client.app.state.account_store
    account = store.add(name="personal")
    store.set_consumer_auth(
        account.id,
        [{"name": "WLSSC", "value": "v", "domain": ".live.com", "path": "/"}],
        "old-token",
        "MSA",
    )
    return account.id


def test_consumer_token_refresh_uses_the_consumer_gate(tmp_path):
    client = _client(tmp_path)
    account_id = _consumer(client)
    calls = []

    async def refresh_consumer(candidate):
        calls.append(candidate)
        return True

    async def ensure_fresh(*args, **kwargs):
        raise AssertionError("consumer admin refresh must not use fallback semantics")

    client.app.state.refresh_scheduler.refresh_consumer = refresh_consumer
    client.app.state.refresh_scheduler.ensure_fresh = ensure_fresh

    response = client.post(f"/admin/accounts/{account_id}/refresh")

    assert response.status_code == 200
    assert response.json()["refreshed"] is True
    assert calls == [account_id]


def test_consumer_token_refresh_failure_is_not_reported_as_success(tmp_path):
    client = _client(tmp_path)
    account_id = _consumer(client)

    async def refresh_consumer(candidate):
        return False

    client.app.state.refresh_scheduler.refresh_consumer = refresh_consumer

    response = client.post(f"/admin/accounts/{account_id}/refresh")

    assert response.status_code == 502
    assert client.app.state.account_store.get(account_id).consumer_token == "old-token"


def test_consumer_cookie_refresh_uses_the_same_combined_gate(tmp_path):
    client = _client(tmp_path)
    account_id = _consumer(client)
    calls = []

    async def refresh_consumer(candidate):
        calls.append(candidate)
        return True

    async def inject_cookies(*args, **kwargs):
        raise AssertionError("consumer cookies must not enter the M365 Chromium path")

    client.app.state.refresh_scheduler.refresh_consumer = refresh_consumer
    client.app.state.refresh_scheduler.inject_cookies = inject_cookies

    response = client.post(f"/admin/accounts/{account_id}/cookie-refresh")

    assert response.status_code == 200
    assert response.json()["provider"] == "consumer"
    assert calls == [account_id]


def test_consumer_cookie_refresh_failure_keeps_the_saved_cookie_state(tmp_path):
    client = _client(tmp_path)
    account_id = _consumer(client)
    calls = []

    async def refresh_consumer(candidate):
        calls.append(candidate)
        return False

    async def inject_cookies(*args, **kwargs):
        raise AssertionError("consumer cookies must not enter the M365 Chromium path")

    client.app.state.refresh_scheduler.refresh_consumer = refresh_consumer
    client.app.state.refresh_scheduler.inject_cookies = inject_cookies

    response = client.post(f"/admin/accounts/{account_id}/cookie-refresh")

    assert response.status_code == 502
    assert calls == [account_id]
    account = client.app.state.account_store.get(account_id)
    assert account.cookie_valid is True
    assert account.cookies == [
        {"name": "WLSSC", "value": "v", "domain": ".live.com", "path": "/"}
    ]


def test_admin_delete_consumer_removes_persisted_browser_profile(tmp_path):
    client = _client(tmp_path)
    store = client.app.state.account_store
    account = store.add(name="personal")
    store.set_consumer_auth(
        account.id,
        [{"name": "WLSSC", "value": "v", "domain": ".live.com", "path": "/"}],
        "old-token",
        "MSA",
        consumer_account_id="home:account-a",
    )
    profile = client.app.state.refresh_scheduler._consumer_profile_dir(
        account.id, "home:account-a"
    )
    profile.mkdir(parents=True)
    (profile / "session-state").write_text("secret", encoding="utf-8")

    response = client.delete(f"/admin/accounts/{account.id}")

    assert response.status_code == 200
    assert store.get(account.id) is None
    assert not profile.exists()
