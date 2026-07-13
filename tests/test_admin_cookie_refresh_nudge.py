from __future__ import annotations

from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="api-key", ADMIN_PASSWORD="admin-pass")))


def _login(client: TestClient) -> None:
    assert client.post("/admin/login", json={"password": "admin-pass"}).status_code == 200


def test_admin_cookie_refresh_calls_inject_with_allow_nudge_true(tmp_path):
    """The admin cookie-refresh button must re-mint all three keys in the same
    injected session regardless of the RT path, so it has to reach inject_cookies
    with allow_nudge=True (mirrors the /v1 wake-up refresh, not the fast user push)."""
    client = make_client(tmp_path)
    _login(client)

    store = client.app.state.account_store
    acc = store.add(name="acct", token="tok")
    store.set_cookies(acc.id, [{"name": "c", "value": "v", "domain": ".microsoft.com", "path": "/"}])

    calls: list[dict] = []

    async def fake_inject_cookies(account_id, cookies, *, allow_nudge=False):
        calls.append({"account_id": account_id, "allow_nudge": allow_nudge, "n": len(cookies)})
        return len(cookies), len(cookies)

    client.app.state.refresh_scheduler.inject_cookies = fake_inject_cookies

    resp = client.post(f"/admin/accounts/{acc.id}/cookie-refresh")

    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0]["account_id"] == acc.id
    assert calls[0]["allow_nudge"] is True


def test_admin_cookie_refresh_without_stored_cookies_returns_400(tmp_path):
    client = make_client(tmp_path)
    _login(client)

    store = client.app.state.account_store
    acc = store.add(name="acct", token="tok")

    resp = client.post(f"/admin/accounts/{acc.id}/cookie-refresh")

    assert resp.status_code == 400
