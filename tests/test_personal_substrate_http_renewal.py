from __future__ import annotations

import asyncio
import time
from urllib.parse import parse_qs, urlencode

import httpx
import pytest

from jwe_helpers import make_jwe
from m365_copilot_openai_proxy import personal_substrate_refresh as psr
from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy.personal_substrate_session import (
    PersonalSubstrateSessionError,
    normalize_personal_substrate_session,
)
from m365_copilot_openai_proxy.refresh_scheduler import RefreshScheduler
from test_personal_substrate_refresh import SCOPE, SUBJECT, TENANT, URL, receipt
from test_personal_substrate_session import SUBJECT as OWNER, session_for
from test_refresh_scheduler_personal_substrate import refreshed_auth


NATIVE = "c0ab8ce9-e9a0-42e7-b064-33d422df41f1"
BROKER = "4765445b-32c6-49b0-83e6-1d93765276ca"
PAGE_URL = URL + "?" + urlencode({"client_id": NATIVE, "brk_client_id": BROKER, "client-request-id": "per-call"})
PAGE_FORM = urlencode({
    "client_id": NATIVE, "scope": SCOPE, "grant_type": "refresh_token", "refresh_token": "page-rt",
    "client_info": "1", "redirect_uri": "brk-multihub://outlook.office.com", "brk_client_id": BROKER,
    "brk_redirect_uri": "https://copilot.com/spalanding", "x-client-SKU": "msal.js.browser",
    "x-client-current-telemetry": "5|61,0,,,|,",
})


def grant(refresh_token="stored-rt"):
    issued = receipt(refresh_token=refresh_token, refresh_token_expires_in=86400)
    return psr._token_receipt(PAGE_URL, PAGE_FORM, issued, SUBJECT)["broker"]


def mock_token_endpoint(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))


def test_page_grant_keeps_only_what_redeems_it_again():
    broker = grant()
    assert broker["refresh_token"] == "stored-rt"
    assert time.time() + 86000 < broker["expires_at"] <= time.time() + 86400
    assert set(broker["form"]) == {"client_id", "scope", "client_info", "redirect_uri", "brk_client_id", "brk_redirect_uri"}
    assert "client-request-id" not in broker["url"] and "brk_client_id=" in broker["url"]
    assert "broker" not in psr._token_receipt(URL, urlencode({"client_id": NATIVE, "scope": SCOPE}), receipt(), SUBJECT)


@pytest.mark.parametrize("url", [
    "https://login.example/" + TENANT + "/oauth2/v2.0/token",
    URL.replace("https://", "http://"),
    URL + "?redirect=https://login.example",
])
def test_stored_grant_cannot_point_anywhere_but_the_personal_token_endpoint(url):
    session = {**session_for(SUBJECT), "broker": {**grant(), "url": url}}
    with pytest.raises(PersonalSubstrateSessionError):
        normalize_personal_substrate_session(session, SUBJECT)


def test_http_renewal_redeems_the_stored_grant_and_keeps_the_rotated_one(monkeypatch):
    posted = {}
    fresh = make_jwe({"kid": "http"})

    def handler(request):
        posted.update(url=str(request.url), form=parse_qs(request.content.decode()), origin=request.headers.get("origin"))
        return httpx.Response(200, json=receipt(access_token=fresh, refresh_token="rotated-rt", refresh_token_expires_in=86000))

    mock_token_endpoint(monkeypatch, handler)
    got = asyncio.run(psr.refresh_personal_substrate_via_rt(
        session={**session_for(SUBJECT), "broker": grant()}, previous_token=make_jwe({"kid": "old"}),
    ))
    assert got["access_token"] == fresh and got["account_id"] == SUBJECT
    assert got["session"]["broker"]["refresh_token"] == "rotated-rt"
    assert posted["form"]["grant_type"] == ["refresh_token"] and posted["form"]["refresh_token"] == ["stored-rt"]
    assert "x-client-SKU" not in posted["form"] and posted["origin"] == "https://copilot.com"


@pytest.mark.parametrize("status,body,code", [
    (400, {"error": "invalid_grant"}, "session_expired"),
    (503, {"error": "temporarily_unavailable"}, "issuance_unavailable"),
])
def test_refused_grant_maps_to_a_safe_failure(monkeypatch, status, body, code):
    mock_token_endpoint(monkeypatch, lambda request: httpx.Response(status, json=body))
    with pytest.raises(psr.PersonalSubstrateRefreshError, match=code):
        asyncio.run(psr.refresh_personal_substrate_via_rt(
            session={**session_for(SUBJECT), "broker": grant()}, previous_token=make_jwe(),
        ))


def scheduler_with_grant(tmp_path):
    store = AccountStore(tmp_path / "accounts.json")
    account = store.add(
        token=make_jwe({"kid": "old"}), substrate_account_id=OWNER,
        personal_substrate_session={**session_for(), "broker": grant()}, expires_at=time.time() - 1,
    )
    return store, account, RefreshScheduler(store, tmp_path / "profiles")


def test_live_grant_renews_without_the_browser_and_stays_encrypted_at_rest(tmp_path, monkeypatch):
    store, account, scheduler = scheduler_with_grant(tmp_path)
    fresh = {**refreshed_auth(), "session": {**session_for(), "broker": grant("rotated-rt")}}

    async def http(*, session, previous_token, proxy_url=""):
        assert session["broker"]["refresh_token"] == "stored-rt"
        return fresh

    async def gate():
        raise AssertionError("A live refresh grant must not open the browser")

    monkeypatch.setattr(psr, "refresh_personal_substrate_via_rt", http)
    scheduler._personal_substrate_gate_factory = lambda account_id: gate
    assert asyncio.run(scheduler.ensure_fresh(account.id)) is True
    assert account.token == fresh["access_token"]
    persisted = (tmp_path / "accounts.json").read_text(encoding="utf-8")
    assert "rotated-rt" not in persisted and "stored-rt" not in persisted
    reloaded = AccountStore(tmp_path / "accounts.json").get(account.id)
    assert reloaded.personal_substrate_session["broker"]["refresh_token"] == "rotated-rt"


def test_refused_grant_falls_back_to_the_browser_once(tmp_path, monkeypatch):
    store, account, scheduler = scheduler_with_grant(tmp_path)
    fresh = refreshed_auth()
    calls = 0

    async def http(**kwargs):
        raise psr.PersonalSubstrateRefreshError("session_expired")

    async def gate():
        nonlocal calls
        calls += 1
        return fresh

    monkeypatch.setattr(psr, "refresh_personal_substrate_via_rt", http)
    scheduler._personal_substrate_gate_factory = lambda account_id: gate
    assert asyncio.run(scheduler.ensure_fresh(account.id)) is True
    assert calls == 1 and account.token == fresh["access_token"]
    assert account.personal_substrate_refresh_error == ""


def test_http_renewal_keeps_a_rotated_token_that_omits_its_lifetime(monkeypatch):
    stored = grant()
    fresh = make_jwe({"kid": "http"})
    mock_token_endpoint(monkeypatch, lambda request: httpx.Response(200, json=receipt(access_token=fresh, refresh_token="rotated-rt")))
    got = asyncio.run(psr.refresh_personal_substrate_via_rt(
        session={**session_for(SUBJECT), "broker": stored}, previous_token=make_jwe({"kid": "old"}),
    ))
    assert got["session"]["broker"]["refresh_token"] == "rotated-rt"
    assert got["session"]["broker"]["expires_at"] == stored["expires_at"]
