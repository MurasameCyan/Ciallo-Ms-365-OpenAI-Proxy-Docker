from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy import refresh_scheduler as refresh_scheduler_module
from m365_copilot_openai_proxy.refresh_scheduler import RefreshScheduler
from m365_copilot_openai_proxy.refresh_via_rt import refresh_via_rt


CLIENT_ID = "4765445b-32c6-49b0-83e6-1d93765276ca"
HOME_TENANT = "11111111-1111-1111-1111-111111111111"
RESOURCE_TENANT = "22222222-2222-2222-2222-222222222222"
OBJECT_ID = "33333333-3333-3333-3333-333333333333"


def _jwt(
    *,
    oid: str = OBJECT_ID,
    tid: str = RESOURCE_TENANT,
    marker: str = "",
    email: str = "person@example.com",
) -> str:
    claims = {
        "aud": "https://substrate.office.com/",
        "exp": int(time.time()) + 3600,
        "email": email,
        "name": "Person",
        "oid": oid,
        "tid": tid,
        "marker": marker,
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def _bound_app(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    account = app.state.account_store.add(name="Person", token=_jwt())
    key = app.state.key_store.add(name="Proxy User", account_id=account.id)
    return app, account, key


def _binding(**overrides) -> dict[str, str]:
    body = {
        "refresh_token": "1.AT4A" + "r" * 200,
        "client_id": CLIENT_ID,
        "authority": HOME_TENANT,
        "tenant_id": RESOURCE_TENANT,
        "object_id": OBJECT_ID,
    }
    body.update(overrides)
    return body


def test_refresh_token_push_requires_a_complete_capture_binding(tmp_path):
    app, account, key = _bound_app(tmp_path)

    response = TestClient(app).post(
        "/user/account/refresh-token",
        headers={"Authorization": f"Bearer {key.key}"},
        json={"refresh_token": "1.AT4A" + "r" * 200},
    )

    assert response.status_code == 400
    assert app.state.account_store.get(account.id).refresh_token == ""


def test_refresh_token_push_rejects_the_wrong_client_or_subject(tmp_path):
    app, account, key = _bound_app(tmp_path)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {key.key}"}

    wrong_client = client.post(
        "/user/account/refresh-token",
        headers=headers,
        json=_binding(client_id="00000000-0000-0000-0000-000000000000"),
    )
    wrong_subject = client.post(
        "/user/account/refresh-token",
        headers=headers,
        json=_binding(object_id="44444444-4444-4444-4444-444444444444"),
    )

    assert wrong_client.status_code == 400
    assert wrong_subject.status_code == 409
    assert app.state.account_store.get(account.id).refresh_token == ""


def test_refresh_token_push_persists_the_verified_authority_and_subject(tmp_path):
    app, account, key = _bound_app(tmp_path)

    response = TestClient(app).post(
        "/user/account/refresh-token",
        headers={"Authorization": f"Bearer {key.key}"},
        json=_binding(),
    )

    assert response.status_code == 200
    stored = app.state.account_store.get(account.id)
    assert stored.refresh_token == _binding()["refresh_token"]
    assert stored.refresh_token_client_id == CLIENT_ID
    assert stored.refresh_token_authority == HOME_TENANT
    assert stored.refresh_token_tenant_id == RESOURCE_TENANT
    assert stored.refresh_token_object_id == OBJECT_ID

    reloaded = AccountStore(persist_path=tmp_path / "accounts.json")
    persisted = reloaded.get(account.id)
    assert persisted.refresh_token_client_id == CLIENT_ID
    assert persisted.refresh_token_authority == HOME_TENANT
    assert persisted.refresh_token_tenant_id == RESOURCE_TENANT
    assert persisted.refresh_token_object_id == OBJECT_ID


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _AsyncClient:
    response = _Response(500, {})
    calls: list[tuple[str, dict, dict]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, *, data: dict, headers: dict):
        type(self).calls.append((url, data, headers))
        return type(self).response


def _rt_account(tmp_path):
    app, account, _ = _bound_app(tmp_path)
    store = app.state.account_store
    store.set_refresh_token(account.id, _binding()["refresh_token"])
    stored = store.get(account.id)
    # These attributes describe the binding that the fixed userscript sends.
    # They are assigned dynamically so this regression test fails by assertion,
    # rather than failing to import before the production fields exist.
    stored.refresh_token_client_id = CLIENT_ID
    stored.refresh_token_authority = HOME_TENANT
    stored.refresh_token_tenant_id = RESOURCE_TENANT
    stored.refresh_token_object_id = OBJECT_ID
    return store, account.id


def test_rt_exchange_reuses_the_captured_authority_and_full_scope(tmp_path, monkeypatch):
    store, account_id = _rt_account(tmp_path)
    _AsyncClient.calls = []
    _AsyncClient.response = _Response(
        200,
        {
            "access_token": _jwt(),
            "refresh_token": "1.AT4A" + "n" * 200,
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    assert asyncio.run(refresh_via_rt(store, account_id)) is True
    assert len(_AsyncClient.calls) == 1
    url, data, headers = _AsyncClient.calls[0]
    assert url == f"https://login.microsoftonline.com/{HOME_TENANT}/oauth2/v2.0/token"
    assert data["client_id"] == CLIENT_ID
    assert set(data["scope"].split()) == {
        "https://substrate.office.com/sydney/.default",
        "openid",
        "profile",
        "offline_access",
    }
    assert headers["Origin"] == "https://m365.cloud.microsoft"


def test_rt_subject_match_allows_email_change_and_updates_identity(
    tmp_path, monkeypatch
):
    store, account_id = _rt_account(tmp_path)
    store.get(account_id).email = "old@example.com"
    _AsyncClient.calls = []
    _AsyncClient.response = _Response(
        200,
        {
            "access_token": _jwt(email="new@example.com"),
            "refresh_token": "1.AT4A" + "rotated" * 40,
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    assert asyncio.run(refresh_via_rt(store, account_id)) is True
    stored = store.get(account_id)
    assert stored.email == "new@example.com"
    assert stored.refresh_token.startswith("1.AT4Arotated")


def test_idp_error_defers_the_rt_before_cdp_fallback(tmp_path, monkeypatch):
    store, account_id = _rt_account(tmp_path)
    _AsyncClient.calls = []
    _AsyncClient.response = _Response(
        400,
        {
            "error": "invalid_grant",
            "error_description": "AADSTS40016: The Identity Provider returned an error.\r\nTrace ID: test",
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    assert asyncio.run(refresh_via_rt(store, account_id)) is False
    stored = store.get(account_id)
    assert stored.refresh_token == _binding()["refresh_token"]
    assert stored.refresh_token_retry_after > time.time()
    assert stored.refresh_token_client_id == CLIENT_ID
    assert stored.refresh_token_authority == HOME_TENANT
    assert stored.refresh_token_tenant_id == RESOURCE_TENANT
    assert stored.refresh_token_object_id == OBJECT_ID


def test_terminal_spa_rt_expiry_clears_the_bad_rt_before_cdp_fallback(
    tmp_path, monkeypatch
):
    store, account_id = _rt_account(tmp_path)
    _AsyncClient.calls = []
    _AsyncClient.response = _Response(
        400,
        {
            "error": "invalid_grant",
            "error_description": "AADSTS700084: The refresh token was issued to a single page app and has a fixed lifetime.\r\nTrace ID: test",
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    assert asyncio.run(refresh_via_rt(store, account_id)) is False
    stored = store.get(account_id)
    assert stored.refresh_token == ""
    assert stored.refresh_token_client_id == ""
    assert stored.refresh_token_authority == ""
    assert stored.refresh_token_tenant_id == ""
    assert stored.refresh_token_object_id == ""


def test_terminal_error_codes_clear_rt_even_without_an_english_description(
    tmp_path, monkeypatch
):
    store, account_id = _rt_account(tmp_path)
    _AsyncClient.calls = []
    _AsyncClient.response = _Response(
        400,
        {
            "error": "invalid_grant",
            "error_codes": [700084],
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    assert asyncio.run(refresh_via_rt(store, account_id)) is False
    assert store.get(account_id).refresh_token == ""


@pytest.mark.parametrize("error_code", [70008, 70043])
def test_expired_or_conditional_access_grant_code_clears_rt(
    tmp_path, monkeypatch, error_code
):
    store, account_id = _rt_account(tmp_path)
    _AsyncClient.calls = []
    _AsyncClient.response = _Response(
        400,
        {
            "error": "invalid_grant",
            "error_codes": [error_code],
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    assert asyncio.run(refresh_via_rt(store, account_id)) is False
    assert store.get(account_id).refresh_token == ""


def test_legacy_unbound_rt_is_dropped_without_calling_aad(tmp_path, monkeypatch):
    app, account, _ = _bound_app(tmp_path)
    store = app.state.account_store
    store.set_refresh_token(account.id, "1.AT4A" + "legacy" * 40)
    _AsyncClient.calls = []
    _AsyncClient.response = _Response(500, {})
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    assert asyncio.run(refresh_via_rt(store, account.id)) is False
    assert _AsyncClient.calls == []
    assert store.get(account.id).refresh_token == ""


def test_concurrent_forced_refreshes_coalesce_one_rt_exchange(tmp_path, monkeypatch):
    app, account, _ = _bound_app(tmp_path)
    store = app.state.account_store
    store.set_refresh_token(account.id, "1.AT4A" + "r" * 200)
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def fake_refresh(accounts, account_id):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        accounts.set_refresh_token(account_id, "1.AT4A" + "n" * 200)
        accounts.update_token(account_id, _jwt())
        return True

    monkeypatch.setattr(refresh_scheduler_module, "refresh_via_rt", fake_refresh)

    async def scenario():
        first = asyncio.create_task(scheduler.ensure_fresh(account.id, force=True))
        await entered.wait()
        second = asyncio.create_task(scheduler.ensure_fresh(account.id, force=True))
        await asyncio.sleep(0)
        release.set()
        assert await asyncio.gather(first, second) == [True, True]

    asyncio.run(scenario())
    assert calls == 1


def test_cookie_session_refresh_can_bypass_rt_and_reach_cdp(tmp_path, monkeypatch):
    app, account, _ = _bound_app(tmp_path)
    store = app.state.account_store
    store.set_refresh_token(account.id, "1.AT4A" + "r" * 200)
    store.set_cookie_status(
        account.id,
        True,
        token_source="cdp",
        expires_at=time.time() + 60,
    )
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    rt_calls = 0
    cdp_calls = 0

    async def fake_rt(account_id: str, *, force: bool = False) -> bool:
        nonlocal rt_calls
        rt_calls += 1
        return True

    async def fake_cdp(account_id: str) -> bool:
        nonlocal cdp_calls
        cdp_calls += 1
        return True

    monkeypatch.setattr(scheduler, "_try_rt_refresh", fake_rt)
    monkeypatch.setattr(scheduler, "_refresh_one", fake_cdp)

    result = asyncio.run(
        scheduler.ensure_fresh(account.id, force=True, allow_rt=False)
    )

    assert result is True
    assert rt_calls == 0
    assert cdp_calls == 1


def test_cookie_keepalive_and_recovery_explicitly_bypass_rt():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "m365_copilot_openai_proxy"
        / "refresh_scheduler.py"
    ).read_text(encoding="utf-8")

    assert source.count("allow_rt=False") >= 2


def test_scheduler_skips_an_rt_during_its_error_backoff(tmp_path, monkeypatch):
    app, account, _ = _bound_app(tmp_path)
    store = app.state.account_store
    store.set_refresh_token(account.id, "1.AT4A" + "r" * 200)
    stored = store.get(account.id)
    stored.refresh_token_retry_after = time.time() + 900
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    rt_calls = 0
    cdp_calls = 0

    async def fake_rt(accounts, account_id: str) -> bool:
        nonlocal rt_calls
        rt_calls += 1
        return False

    async def fake_cdp(account_id: str) -> bool:
        nonlocal cdp_calls
        cdp_calls += 1
        return True

    monkeypatch.setattr(refresh_scheduler_module, "refresh_via_rt", fake_rt)
    monkeypatch.setattr(scheduler, "_refresh_one", fake_cdp)

    assert asyncio.run(scheduler.ensure_fresh(account.id, force=True)) is True
    assert rt_calls == 0
    assert cdp_calls == 1


class _BlockingClient(_AsyncClient):
    entered: asyncio.Event
    release: asyncio.Event

    async def post(self, url: str, *, data: dict, headers: dict):
        type(self).calls.append((url, data, headers))
        type(self).entered.set()
        await type(self).release.wait()
        return type(self).response


def test_rt_response_cannot_overwrite_a_newer_userscript_push(tmp_path, monkeypatch):
    store, account_id = _rt_account(tmp_path)
    original_token = store.get(account_id).token
    new_rt = "1.AT4A" + "newer" * 40
    new_token = _jwt(oid=OBJECT_ID, tid=RESOURCE_TENANT, marker="newer")
    _BlockingClient.calls = []
    _BlockingClient.response = _Response(
        200,
        {
            "access_token": _jwt(),
            "refresh_token": "1.AT4A" + "stale" * 40,
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _BlockingClient)

    async def scenario():
        _BlockingClient.entered = asyncio.Event()
        _BlockingClient.release = asyncio.Event()
        task = asyncio.create_task(refresh_via_rt(store, account_id))
        await _BlockingClient.entered.wait()
        assert store.get(account_id).token == original_token
        store.set_refresh_token(
            account_id,
            new_rt,
            client_id=CLIENT_ID,
            authority=HOME_TENANT,
            tenant_id=RESOURCE_TENANT,
            object_id=OBJECT_ID,
        )
        store.update_token(account_id, new_token)
        _BlockingClient.release.set()
        assert await task is False

    asyncio.run(scenario())
    stored = store.get(account_id)
    assert stored.refresh_token == new_rt
    assert stored.token == new_token


class _FailingClient(_AsyncClient):
    async def post(self, url: str, *, data: dict, headers: dict):
        raise httpx.ConnectError("temporary network failure")


def test_network_failure_backs_off_without_deleting_the_rt(tmp_path, monkeypatch):
    store, account_id = _rt_account(tmp_path)
    monkeypatch.setattr(httpx, "AsyncClient", _FailingClient)

    assert asyncio.run(refresh_via_rt(store, account_id)) is False
    stored = store.get(account_id)
    assert stored.refresh_token == _binding()["refresh_token"]
    assert stored.refresh_token_retry_after > time.time()


def test_malformed_success_response_backs_off_instead_of_hot_looping(
    tmp_path, monkeypatch
):
    store, account_id = _rt_account(tmp_path)
    _AsyncClient.calls = []
    _AsyncClient.response = _Response(200, {})
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    assert asyncio.run(refresh_via_rt(store, account_id)) is False
    stored = store.get(account_id)
    assert stored.refresh_token == _binding()["refresh_token"]
    assert stored.refresh_token_retry_after > time.time()


def test_aadsts40016_immediately_falls_back_to_cdp_then_skips_hot_retry(
    tmp_path, monkeypatch
):
    store, account_id = _rt_account(tmp_path)
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    _AsyncClient.calls = []
    _AsyncClient.response = _Response(
        400,
        {
            "error": "invalid_grant",
            "error_description": "AADSTS40016: The Identity Provider returned an error.\r\nTrace ID: test",
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)
    cdp_calls = 0

    async def fake_cdp(account_id: str) -> bool:
        nonlocal cdp_calls
        cdp_calls += 1
        return True

    monkeypatch.setattr(scheduler, "_refresh_one", fake_cdp)

    assert asyncio.run(scheduler.ensure_fresh(account_id, force=True)) is True
    assert asyncio.run(scheduler.ensure_fresh(account_id, force=True)) is True
    assert len(_AsyncClient.calls) == 1
    assert cdp_calls == 2


def test_concurrent_aad_failure_coalesces_the_cdp_fallback(tmp_path, monkeypatch):
    store, account_id = _rt_account(tmp_path)
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    _AsyncClient.calls = []
    _AsyncClient.response = _Response(
        400,
        {
            "error": "invalid_grant",
            "error_description": "AADSTS40016: The Identity Provider returned an error.",
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)
    cdp_entered = asyncio.Event()
    cdp_release = asyncio.Event()
    cdp_calls = 0

    async def fake_cdp(account_id: str) -> bool:
        nonlocal cdp_calls
        cdp_calls += 1
        cdp_entered.set()
        await cdp_release.wait()
        store.update_token(account_id, _jwt(marker="cdp-fresh"))
        return True

    monkeypatch.setattr(scheduler, "_refresh_one", fake_cdp)

    async def scenario():
        first = asyncio.create_task(scheduler.ensure_fresh(account_id, force=True))
        await cdp_entered.wait()
        second = asyncio.create_task(scheduler.ensure_fresh(account_id, force=True))
        await asyncio.sleep(0)
        cdp_release.set()
        assert await asyncio.gather(first, second) == [True, True]

    asyncio.run(scenario())
    assert len(_AsyncClient.calls) == 1
    assert cdp_calls == 1


def test_concurrent_aad_failure_shares_a_failed_cdp_fallback(tmp_path, monkeypatch):
    store, account_id = _rt_account(tmp_path)
    scheduler = RefreshScheduler(store, tmp_path / "profiles")
    _AsyncClient.calls = []
    _AsyncClient.response = _Response(
        400,
        {
            "error": "invalid_grant",
            "error_description": "AADSTS40016: The Identity Provider returned an error.",
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)
    cdp_entered = asyncio.Event()
    cdp_release = asyncio.Event()
    cdp_calls = 0

    async def fake_cdp(account_id: str) -> bool:
        nonlocal cdp_calls
        cdp_calls += 1
        cdp_entered.set()
        await cdp_release.wait()
        return False

    monkeypatch.setattr(scheduler, "_refresh_one", fake_cdp)

    async def scenario():
        first = asyncio.create_task(scheduler.ensure_fresh(account_id, force=True))
        await cdp_entered.wait()
        second = asyncio.create_task(scheduler.ensure_fresh(account_id, force=True))
        await asyncio.sleep(0)
        cdp_release.set()
        assert await asyncio.gather(first, second) == [False, False]

    asyncio.run(scenario())
    assert len(_AsyncClient.calls) == 1
    assert cdp_calls == 1
