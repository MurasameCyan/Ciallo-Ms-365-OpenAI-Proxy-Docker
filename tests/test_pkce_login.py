"""Interactive PKCE login + RT-derived media tokens: the browser-free credential path.

Every token the pool holds used to come out of a live browser session, which is
why cookie keepalive, a headless Chromium and a media seed URL exist. These tests
pin the replacement: one authorization-code sign-in against the *native* Office
Copilot client, after which the substrate token, the Teams media token and the
Designer token are all plain HTTP hops off the same refresh token.

The AAD calls are stubbed -- what is asserted is the request shape AAD actually
cares about (PKCE method, native client id, no Origin header) and that a bad
sign-in can never overwrite the identity an account is already bound to.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.m365_cloud_client import (
    _TOKEN_CACHE,
    CloudSessionError,
    _cloud_token,
)
from m365_copilot_openai_proxy.pkce_login import (
    NATIVE_REDIRECT_URI,
    PENDING_TTL_SECONDS,
    PkceLogins,
    authorize_url,
    code_challenge,
    make_verifier,
    parse_callback,
)
from m365_copilot_openai_proxy.refresh_via_rt import (
    M365_DESIGNER_SCOPE,
    M365_MEDIA_SCOPE,
    M365_NATIVE_CLIENT_ID,
    M365_REFRESH_CLIENT_ID,
    _token_request_headers,
    mint_scoped_token,
)

TENANT = "11111111-1111-1111-1111-111111111111"
OBJECT_ID = "33333333-3333-3333-3333-333333333333"
OTHER_OBJECT_ID = "44444444-4444-4444-4444-444444444444"
RT = "1.AT4A" + "r" * 200


def _jwt(*, aud: str = "https://substrate.office.com/sydney", oid: str = OBJECT_ID, **extra) -> str:
    claims = {
        "aud": aud,
        "exp": int(time.time()) + 3600,
        "oid": oid,
        "tid": TENANT,
        "appid": M365_NATIVE_CLIENT_ID,
        "upn": "person@example.com",
        "name": "Person",
    }
    claims.update(extra)
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _AsyncClient:
    """Stands in for httpx.AsyncClient.

    ``responses`` is drained first when set (a sign-in now makes three calls in a
    row: the code exchange, then one scope hop per media key); ``response``
    answers everything else.
    """

    response = _Response(500, {})
    responses: list = []
    calls: list[tuple[str, dict, dict]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, *, data: dict, headers: dict):
        type(self).calls.append((url, data, headers))
        queued = type(self).responses
        return queued.pop(0) if queued else type(self).response


@pytest.fixture
def aad(monkeypatch):
    _AsyncClient.calls = []
    _AsyncClient.responses = []
    _AsyncClient.response = _Response(500, {})
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)
    return _AsyncClient


@pytest.fixture
def admin(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    client = TestClient(app)
    assert client.post("/admin/login", json={"password": "admin-key"}).status_code == 200
    account = app.state.account_store.add(name="Person", token=_jwt())
    return app, client, account


def _bind_rt(app, account_id, *, client_id=M365_NATIVE_CLIENT_ID):
    app.state.account_store.set_refresh_token(
        account_id,
        RT,
        client_id=client_id,
        authority=TENANT,
        tenant_id=TENANT,
        object_id=OBJECT_ID,
    )


# --- pure PKCE mechanics -------------------------------------------------


def test_code_challenge_is_the_unpadded_s256_of_the_verifier():
    verifier = make_verifier()

    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    assert code_challenge(verifier) == expected.decode().rstrip("=")
    assert "=" not in code_challenge(verifier)


def test_authorize_url_pins_the_native_client_and_forces_account_choice():
    url = authorize_url(authority=TENANT, state="st", verifier="v" * 43, login_hint="p@e.com")

    assert url.startswith(f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize?")
    assert f"client_id={M365_NATIVE_CLIENT_ID}" in url
    assert "code_challenge_method=S256" in url
    assert "offline_access" in url  # no RT, no point doing any of this
    # A browser already signed in as somebody else must not silently bind here.
    assert "prompt=select_account" in url
    assert "login_hint=p%40e.com" in url
    assert NATIVE_REDIRECT_URI.replace(":", "%3A").replace("/", "%2F") in url


@pytest.mark.parametrize(
    "pasted,code,error",
    [
        (f"{NATIVE_REDIRECT_URI}?code=abc123&state=st", "abc123", ""),
        ("?code=abc123&state=st", "abc123", ""),
        ("code=abc123&state=st", "abc123", ""),
        ("A" * 40, "A" * 40, ""),
        ("", "", "nothing pasted"),
        ("nope", "", "not a callback URL or code"),
        (f"{NATIVE_REDIRECT_URI}?state=st", "", "no code"),
    ],
)
def test_parse_callback_accepts_what_operators_actually_paste(pasted, code, error):
    got_code, _state, got_error = parse_callback(pasted)

    assert got_code == code
    assert (error in got_error) if error else not got_error


def test_parse_callback_surfaces_the_aad_error_instead_of_a_blank_failure():
    _code, _state, error = parse_callback(
        f"{NATIVE_REDIRECT_URI}?error=access_denied&error_description=AADSTS65004%3A+user+declined"
    )

    assert "access_denied" in error and "AADSTS65004" in error


def test_a_started_login_is_single_use():
    logins = PkceLogins()
    started = logins.start("acct_1", authority=TENANT)

    assert logins.take(started["state"])["account_id"] == "acct_1"
    assert logins.take(started["state"]) is None  # a code is redeemable once


def test_an_expired_login_cannot_be_redeemed():
    logins = PkceLogins()
    started = logins.start("acct_1")
    logins._pending[started["state"]]["created_at"] -= PENDING_TTL_SECONDS + 1

    assert logins.take(started["state"]) is None
    assert logins.only_pending() is None


def test_only_pending_needs_exactly_one_candidate():
    logins = PkceLogins()
    logins.start("acct_1")
    assert logins.only_pending()["account_id"] == "acct_1"

    logins.start("acct_2")
    assert logins.only_pending() is None  # ambiguous: refuse to guess


# --- AAD request shape ---------------------------------------------------


def test_only_the_spa_client_sends_an_origin_header():
    """AAD applies SPA rules (24h RT cap) to any request carrying Origin."""
    assert _token_request_headers(M365_REFRESH_CLIENT_ID)["Origin"]
    assert "Origin" not in _token_request_headers(M365_NATIVE_CLIENT_ID)


def test_pkce_code_exchange_is_a_native_public_client_redemption(admin, aad):
    app, client, account = admin
    started = client.post("/admin/pkce/start", json={"account_id": account.id}).json()
    aad.response = _Response(200, {"access_token": _jwt(), "refresh_token": RT})

    client.post(
        "/admin/pkce/complete",
        json={"callback_url": f"{NATIVE_REDIRECT_URI}?code=abc123&state={started['state']}"},
    )

    # calls[0], not calls[-1]: completing a sign-in goes straight on to mint the
    # two media keys, which are refresh_token grants on the same stub.
    _url, data, headers = aad.calls[0]
    assert data["grant_type"] == "authorization_code"
    assert data["client_id"] == M365_NATIVE_CLIENT_ID
    assert data["redirect_uri"] == NATIVE_REDIRECT_URI
    assert data["code_verifier"] and len(data["code_verifier"]) >= 43
    assert "Origin" not in headers
    assert "client_secret" not in data  # public client: there is no secret to leak


# --- /admin/pkce endpoints -----------------------------------------------


def test_start_requires_admin(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    account = app.state.account_store.add(name="Person", token=_jwt())

    r = TestClient(app).post("/admin/pkce/start", json={"account_id": account.id})

    assert r.status_code in (401, 403)


def test_start_targets_the_accounts_own_tenant(admin):
    _app, client, account = admin

    body = client.post("/admin/pkce/start", json={"account_id": account.id}).json()

    assert body["authority"] == TENANT
    assert f"/{TENANT}/oauth2/v2.0/authorize" in body["auth_url"]
    assert body["state"] in body["auth_url"]


def test_start_rejects_unknown_and_consumer_accounts(admin):
    app, client, _account = admin
    consumer = app.state.account_store.add(name="Personal")
    app.state.account_store.set_consumer_auth(consumer.id, [{"name": "c"}], "consumer-token")

    assert client.post("/admin/pkce/start", json={"account_id": "nope"}).status_code == 404
    assert client.post("/admin/pkce/start", json={"account_id": consumer.id}).status_code == 400


def test_complete_stores_the_token_and_a_native_client_refresh_token(admin, aad):
    app, client, account = admin
    started = client.post("/admin/pkce/start", json={"account_id": account.id}).json()
    fresh = _jwt(upn="person@example.com")
    aad.response = _Response(200, {"access_token": fresh, "refresh_token": RT})

    r = client.post(
        "/admin/pkce/complete",
        json={"callback_url": f"{NATIVE_REDIRECT_URI}?code=abc123&state={started['state']}"},
    )

    assert r.status_code == 200 and r.json()["has_refresh_token"] is True
    stored = app.state.account_store.get(account.id)
    assert stored.token == fresh
    assert stored.refresh_token == RT
    # The binding is what lets the refresh path trust this RT later.
    assert stored.refresh_token_client_id == M365_NATIVE_CLIENT_ID
    assert stored.refresh_token_tenant_id == TENANT
    assert stored.refresh_token_object_id == OBJECT_ID
    # The tokens themselves never travel back to the browser.
    assert RT not in r.text and fresh not in r.text


def test_complete_refuses_a_different_microsoft_identity(admin, aad):
    """A wrong account in the browser must not hijack a bound pool account."""
    app, client, account = admin
    started = client.post("/admin/pkce/start", json={"account_id": account.id}).json()
    aad.response = _Response(200, {"access_token": _jwt(oid=OTHER_OBJECT_ID), "refresh_token": RT})

    r = client.post(
        "/admin/pkce/complete",
        json={"callback_url": f"{NATIVE_REDIRECT_URI}?code=abc123&state={started['state']}"},
    )

    assert r.status_code == 409
    assert app.state.account_store.get(account.id).refresh_token == ""


def test_complete_refuses_a_sign_in_that_returns_no_refresh_token(admin, aad):
    app, client, account = admin
    started = client.post("/admin/pkce/start", json={"account_id": account.id}).json()
    aad.response = _Response(200, {"access_token": _jwt()})

    r = client.post(
        "/admin/pkce/complete",
        json={"callback_url": f"{NATIVE_REDIRECT_URI}?code=abc123&state={started['state']}"},
    )

    assert r.status_code == 502
    assert app.state.account_store.get(account.id).refresh_token == ""


def test_complete_refuses_a_token_for_the_wrong_audience(admin, aad):
    app, client, account = admin
    started = client.post("/admin/pkce/start", json={"account_id": account.id}).json()
    aad.response = _Response(200, {"access_token": _jwt(aud="https://graph.microsoft.com"), "refresh_token": RT})

    r = client.post(
        "/admin/pkce/complete",
        json={"callback_url": f"{NATIVE_REDIRECT_URI}?code=abc123&state={started['state']}"},
    )

    assert r.status_code == 502
    assert app.state.account_store.get(account.id).refresh_token == ""


def test_complete_without_a_live_login_is_rejected_before_calling_aad(admin, aad):
    _app, client, _account = admin

    r = client.post(
        "/admin/pkce/complete",
        json={"callback_url": f"{NATIVE_REDIRECT_URI}?code=abc123&state=never-started"},
    )

    assert r.status_code == 400
    assert aad.calls == []


def test_complete_reports_the_aad_error_rather_than_a_bare_502(admin, aad):
    _app, client, account = admin
    started = client.post("/admin/pkce/start", json={"account_id": account.id}).json()
    aad.response = _Response(
        400, {"error": "invalid_grant", "error_description": "AADSTS54005: code already redeemed"}
    )

    r = client.post(
        "/admin/pkce/complete",
        json={"callback_url": f"{NATIVE_REDIRECT_URI}?code=abc123&state={started['state']}"},
    )

    assert r.status_code == 502
    assert "AADSTS54005" in r.text


# --- media / designer tokens off the same RT -----------------------------


def test_mint_produces_a_media_token_and_describes_it_without_leaking_it(admin, aad):
    app, client, account = admin
    _bind_rt(app, account.id)
    media = _jwt(aud="https://ic3.teams.office.com")
    aad.response = _Response(200, {"access_token": media})

    r = client.post("/admin/pkce/mint", json={"account_id": account.id, "kind": "media"})

    assert r.status_code == 200
    body = r.json()
    assert body["aud"] == "https://ic3.teams.office.com"
    assert body["scope"] == M365_MEDIA_SCOPE
    assert media not in r.text
    assert app.state.account_store.get(account.id).media_auth_token == media
    _url, data, headers = aad.calls[-1]
    assert data["grant_type"] == "refresh_token"
    assert data["scope"].startswith(M365_MEDIA_SCOPE)
    assert "offline_access" in data["scope"]  # or the RT chain ends here
    assert "Origin" not in headers


def test_mint_handles_the_designer_token_being_an_opaque_jwe(admin, aad):
    app, client, account = admin
    _bind_rt(app, account.id)
    jwe = "eyJhbGciOiJSU0EtT0FFUCJ9.a.b.c.d"
    aad.response = _Response(200, {"access_token": jwe})

    r = client.post("/admin/pkce/mint", json={"account_id": account.id, "kind": "designer"})

    assert r.status_code == 200 and r.json()["format"] == "opaque"
    assert r.json()["scope"] == M365_DESIGNER_SCOPE
    assert app.state.account_store.get(account.id).designer_auth_token == jwe


def test_mint_rejects_an_unknown_audience(admin):
    _app, client, account = admin

    r = client.post("/admin/pkce/mint", json={"account_id": account.id, "kind": "graph"})

    assert r.status_code == 400


def test_mint_persists_a_rotated_refresh_token(admin, aad):
    """Dropping the rotated RT would strand the chain on the next hop."""
    app, client, account = admin
    _bind_rt(app, account.id)
    rotated = "1.AT4A" + "n" * 200
    aad.response = _Response(200, {"access_token": _jwt(aud="https://ic3.teams.office.com"), "refresh_token": rotated})

    client.post("/admin/pkce/mint", json={"account_id": account.id, "kind": "media"})

    stored = app.state.account_store.get(account.id)
    assert stored.refresh_token == rotated
    assert stored.refresh_token_client_id == M365_NATIVE_CLIENT_ID  # binding survives


def test_mint_refuses_an_unbound_refresh_token_without_calling_aad(admin, aad):
    app, client, account = admin
    app.state.account_store.set_refresh_token(account.id, RT)  # no client/authority binding

    r = client.post("/admin/pkce/mint", json={"account_id": account.id, "kind": "media"})

    assert r.status_code == 502 and "binding" in r.text
    assert aad.calls == []


def test_mint_surfaces_a_refused_scope_instead_of_storing_junk(admin, aad):
    app, client, account = admin
    _bind_rt(app, account.id)
    aad.response = _Response(
        400, {"error": "invalid_grant", "error_description": "AADSTS65001: no consent for resource"}
    )

    r = client.post("/admin/pkce/mint", json={"account_id": account.id, "kind": "designer"})

    assert r.status_code == 502 and "AADSTS65001" in r.text
    assert app.state.account_store.get(account.id).designer_auth_token == ""


def test_mint_scoped_token_needs_a_stored_rt(tmp_path):
    from m365_copilot_openai_proxy.account_store import AccountStore

    store = AccountStore(persist_path=tmp_path / "accounts.json")
    account = store.add(name="Person", token=_jwt())

    token, error = asyncio.run(mint_scoped_token(store, account.id, M365_MEDIA_SCOPE))

    assert token == "" and "no stored refresh_token" in error


# --- cloud session management is another hop off the same RT -------------


def test_cloud_management_redeems_the_rt_with_the_client_that_issued_it(admin, aad):
    """Regression: the stored binding is a 4-tuple, and its client id matters.

    Unpacking it as three values raised "too many values to unpack (expected 3)"
    for every bound account, which the consoles showed as "cloud session
    management unavailable" and which also left cleanup deleting local rows only.
    Hardcoding the SPA client instead breaks it the other way: AAD applies SPA
    rules to any redemption carrying Origin.
    """
    app, _client, account = admin
    _bind_rt(app, account.id)
    _TOKEN_CACHE.clear()
    aad.response = _Response(200, {"access_token": _jwt(aud="https://m365.cloud.microsoft/v2/")})

    token = asyncio.run(_cloud_token(app.state.account_store, account.id))

    assert token
    _url, data, headers = aad.calls[-1]
    assert data["client_id"] == M365_NATIVE_CLIENT_ID
    assert "Origin" not in headers
    # No offline_access: this hop must not rotate the RT the substrate path owns.
    assert data["scope"] == "https://m365.cloud.microsoft/v2/.default"
    assert app.state.account_store.get(account.id).refresh_token == RT


def test_cloud_management_keeps_the_spa_origin_for_an_spa_bound_account(admin, aad):
    app, _client, account = admin
    _bind_rt(app, account.id, client_id=M365_REFRESH_CLIENT_ID)
    _TOKEN_CACHE.clear()
    aad.response = _Response(200, {"access_token": _jwt(aud="https://m365.cloud.microsoft/v2/")})

    asyncio.run(_cloud_token(app.state.account_store, account.id))

    _url, data, headers = aad.calls[-1]
    assert data["client_id"] == M365_REFRESH_CLIENT_ID
    assert headers["Origin"] == "https://m365.cloud.microsoft"


def test_cloud_management_accepts_the_encrypted_token_the_native_client_gets(admin, aad):
    """Measured 2026-08-17: for this audience the native client is handed a
    five-segment RSA-OAEP JWE, not a JWT. POST /chat takes it as a Bearer token
    verbatim, so the identity check has to read the id_token minted alongside it
    instead of the access token -- decoding the access token raised a UnicodeDecodeError
    and every cloud call reported "token exchange returned an unusable response".
    """
    app, _client, account = admin
    _bind_rt(app, account.id)
    _TOKEN_CACHE.clear()
    jwe = "eyJhbGciOiJSU0EtT0FFUCJ9.a.b.c.d"
    aad.response = _Response(200, {"access_token": jwe, "id_token": _jwt(), "expires_in": 5239})

    assert asyncio.run(_cloud_token(app.state.account_store, account.id)) == jwe


def test_cloud_management_refuses_an_opaque_token_it_cannot_attribute(admin, aad):
    """No id_token either: an unverifiable subject must not be acted on."""
    app, _client, account = admin
    _bind_rt(app, account.id)
    _TOKEN_CACHE.clear()
    aad.response = _Response(200, {"access_token": "eyJhbGciOiJSU0EtT0FFUCJ9.a.b.c.d", "expires_in": 5239})

    with pytest.raises(CloudSessionError):
        asyncio.run(_cloud_token(app.state.account_store, account.id))


def test_cloud_unavailable_reasons_are_written_in_chinese(admin):
    """These strings land verbatim in the session view's warning tooltip.

    ``routes_sessions._cloud_note`` builds "<account>: <str(exc)>" and both pages
    show it as-is, so the message IS the user-facing copy -- an English cause
    line is a UI regression, not just a log detail.
    """
    app, _client, account = admin
    _TOKEN_CACHE.clear()

    with pytest.raises(CloudSessionError) as no_rt:
        asyncio.run(_cloud_token(app.state.account_store, account.id))

    app.state.account_store.get(account.id).provider = "consumer"
    with pytest.raises(CloudSessionError) as consumer:
        asyncio.run(_cloud_token(app.state.account_store, account.id))

    assert "个人版" in str(consumer.value), str(consumer.value)
    for raised in (no_rt, consumer):
        message = str(raised.value)
        assert any("一" <= ch <= "鿿" for ch in message), f"not Chinese: {message}"


def test_cloud_management_keeps_the_rotated_refresh_token(admin, aad):
    """AAD rotates it even though this hop never asks for offline_access."""
    app, _client, account = admin
    _bind_rt(app, account.id)
    _TOKEN_CACHE.clear()
    rotated = "1.AT4A" + "n" * 200
    aad.response = _Response(
        200,
        {"access_token": _jwt(aud="https://m365.cloud.microsoft/v2/"), "refresh_token": rotated, "expires_in": 5239},
    )

    asyncio.run(_cloud_token(app.state.account_store, account.id))

    stored = app.state.account_store.get(account.id)
    assert stored.refresh_token == rotated
    assert stored.refresh_token_client_id == M365_NATIVE_CLIENT_ID  # binding survives


# --- both media keys come with the sign-in -------------------------------


def test_completing_a_sign_in_mints_both_media_keys_in_one_go(admin, aad):
    """Nothing else mints them until a media fetch needs one -- by which time a
    real request is already failing -- so the sign-in takes both up front."""
    app, client, account = admin
    started = client.post("/admin/pkce/start", json={"account_id": account.id}).json()
    media, jwe = _jwt(aud="https://ic3.teams.office.com"), "eyJhbGciOiJSU0EtT0FFUCJ9.a.b.c.d"
    aad.responses = [
        _Response(200, {"access_token": _jwt(), "refresh_token": RT}),
        _Response(200, {"access_token": media}),
        _Response(200, {"access_token": jwe}),
    ]

    r = client.post(
        "/admin/pkce/complete",
        json={"callback_url": f"{NATIVE_REDIRECT_URI}?code=abc123&state={started['state']}"},
    )

    assert r.status_code == 200
    stored = app.state.account_store.get(account.id)
    assert stored.media_auth_token == media
    assert stored.designer_auth_token == jwe
    keys = r.json()["media_keys"]
    assert keys["media"]["status"] == "ok" and keys["media"]["aud"] == "https://ic3.teams.office.com"
    assert keys["designer"]["status"] == "ok" and keys["designer"]["format"] == "opaque"
    assert media not in r.text and jwe not in r.text
    scopes = [data["scope"] for _url, data, _headers in aad.calls[1:]]
    assert scopes[0].startswith(M365_MEDIA_SCOPE)
    assert scopes[1].startswith(M365_DESIGNER_SCOPE)


def test_a_media_key_that_cannot_be_minted_does_not_undo_the_sign_in(admin, aad):
    """The account is already usable for chat; only media is missing."""
    app, client, account = admin
    started = client.post("/admin/pkce/start", json={"account_id": account.id}).json()
    aad.responses = [
        _Response(200, {"access_token": _jwt(), "refresh_token": RT}),
        _Response(400, {"error": "invalid_grant", "error_description": "AADSTS65001: no consent"}),
        _Response(200, {"access_token": "eyJhbGciOiJSU0EtT0FFUCJ9.a.b.c.d"}),
    ]

    r = client.post(
        "/admin/pkce/complete",
        json={"callback_url": f"{NATIVE_REDIRECT_URI}?code=abc123&state={started['state']}"},
    )

    assert r.status_code == 200 and r.json()["has_refresh_token"] is True
    assert app.state.account_store.get(account.id).refresh_token == RT
    keys = r.json()["media_keys"]
    assert keys["media"]["status"] == "error" and "AADSTS65001" in keys["media"]["error"]
    assert keys["designer"]["status"] == "ok"  # one refusal does not skip the other


# --- the same three steps on /user ---------------------------------------


def _user(app, account_id: str) -> dict:
    key = app.state.key_store.add(name="Proxy User", account_id=account_id)
    return {"Authorization": f"Bearer {key.key}"}


def test_a_user_signs_in_their_own_bound_account_without_naming_it(admin, aad):
    app, client, account = admin
    headers = _user(app, account.id)
    started = client.post("/user/pkce/start", headers=headers).json()
    aad.responses = [_Response(200, {"access_token": _jwt(), "refresh_token": RT})]

    r = client.post(
        "/user/pkce/complete",
        headers=headers,
        json={"callback_url": f"{NATIVE_REDIRECT_URI}?code=abc123&state={started['state']}"},
    )

    assert started["authority"] == TENANT
    assert r.status_code == 200 and r.json()["account_id"] == account.id
    assert app.state.account_store.get(account.id).refresh_token_client_id == M365_NATIVE_CLIENT_ID


def test_a_user_cannot_finish_somebody_elses_sign_in(admin, aad):
    """A bare code has no state, so completing it falls back to the single
    outstanding login -- which must not be another account's."""
    app, client, account = admin
    other = app.state.account_store.add(name="Colleague", token=_jwt(oid=OTHER_OBJECT_ID))
    headers = _user(app, other.id)
    client.post("/admin/pkce/start", json={"account_id": account.id})  # not theirs
    aad.response = _Response(200, {"access_token": _jwt(), "refresh_token": RT})

    r = client.post("/user/pkce/complete", headers=headers, json={"callback_url": "A" * 40})

    assert r.status_code == 400
    assert aad.calls == []  # rejected before AAD, and the login is still pending
    assert app.state.account_store.get(account.id).refresh_token == ""
    assert client.post("/admin/pkce/complete", json={"callback_url": "A" * 40}).status_code == 200


def test_the_user_endpoints_need_a_key_bound_to_an_m365_account(admin, aad):
    app, client, account = admin
    unbound = _user(app, "")
    consumer = app.state.account_store.add(name="Personal")
    app.state.account_store.set_consumer_auth(consumer.id, [{"name": "c"}], "consumer-token")

    assert client.post("/user/pkce/start").status_code == 401
    assert client.post("/user/pkce/start", headers=unbound).status_code == 400
    assert client.post("/user/pkce/start", headers=_user(app, consumer.id)).status_code == 400
    assert client.post("/user/pkce/mint", headers=_user(app, account.id), json={"kind": "graph"}).status_code == 400
    assert aad.calls == []


def test_a_user_mints_media_keys_for_their_own_account_only(admin, aad):
    app, client, account = admin
    _bind_rt(app, account.id)
    media = _jwt(aud="https://ic3.teams.office.com")
    aad.response = _Response(200, {"access_token": media})

    r = client.post(
        "/user/pkce/mint",
        headers=_user(app, account.id),
        # An account_id in the body is ignored: the key decides whose account it is.
        json={"kind": "media", "account_id": "acct_somebody_else"},
    )

    assert r.status_code == 200 and r.json()["aud"] == "https://ic3.teams.office.com"
    assert media not in r.text
    assert app.state.account_store.get(account.id).media_auth_token == media


# --- the panel, on both consoles -----------------------------------------

_PKCE_KEYS = (
    "pkce_start", "pkce_finish", "pkce_paste_ph", "pkce_started", "pkce_done",
    "pkce_starting", "pkce_finishing", "pkce_need_paste",
    "pkce_open_manually", "pkce_keys_ok", "pkce_keys_failed",
)


def test_the_login_panel_is_wired_into_the_account_drawer():
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
    from m365_copilot_openai_proxy.template_pkce import _ADMIN_PKCE_JS

    assert _ADMIN_PKCE_JS in _ADMIN_HTML
    assert "+_pkcePanel(a)" in _ADMIN_HTML  # rendered inside the existing drawer
    # Both languages label every string the panel can show.
    for key in _PKCE_KEYS:
        assert _ADMIN_HTML.count(f"{key}:'") == 2, key


def test_the_same_login_panel_is_offered_on_the_user_page():
    from m365_copilot_openai_proxy.template_pkce import _PKCE_JS, _USER_PKCE_JS
    from m365_copilot_openai_proxy.template_user import _USER_HTML
    from m365_copilot_openai_proxy.template_user_account_js import _USER_ACCOUNT_JS

    assert _USER_PKCE_JS in _USER_HTML
    assert _PKCE_JS in _USER_PKCE_JS  # one implementation, not a second copy
    assert "'/user/pkce'" in _USER_PKCE_JS
    # The panel is only ever filled in by the account render, so that call is the
    # whole wiring: without it the container stays empty.
    assert 'id="pkce-panel"' in _USER_HTML
    assert "renderUserPkce(d.account||null)" in _USER_ACCOUNT_JS
    for key in _PKCE_KEYS + ("pkce_section_title", "pkce_no_account"):
        assert _USER_HTML.count(f"{key}:'") == 2, key


def test_the_panel_is_offered_for_m365_accounts_only(tmp_path):
    """Personal Copilot is MSA + Cloudflare; an AAD sign-in cannot help it."""
    import shutil
    import subprocess

    from m365_copilot_openai_proxy.template_pkce import _ADMIN_PKCE_JS

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for inline UI behavior tests")
    script = "\n".join(
        [
            "const assert=require('assert');",
            "function t(k){return k}",
            "function esc(v){return String(v??'')}",
            _ADMIN_PKCE_JS,
            "const m365=_pkcePanel({id:'acct_1',provider:'m365'});",
            "assert.ok(m365.includes(\"pkceStart('acct_1')\"),m365);",
            "assert.ok(m365.includes(\"pkceComplete('acct_1')\"),m365);",
            "assert.ok(m365.includes('pkce-cb-acct_1'),m365);",
            # Two steps only: signing in mints both media keys server-side, so a
            # "mint key" button (and the hint that explained it) would be noise.
            "assert.ok(!m365.includes('pkceMint'),m365);",
            "assert.ok(!m365.includes('pkce_hint'),m365);",
            "assert.strictEqual(_pkcePanel({id:'acct_2',provider:'consumer'}),'');",
            # A missing provider is the historical M365 default, not a hole.
            "assert.ok(_pkcePanel({id:'acct_3'}).length>0);",
        ]
    )
    path = tmp_path / "pkce-panel.js"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")

    assert result.returncode == 0, (result.stderr or "") + (result.stdout or "")


def test_the_user_panel_is_not_rebuilt_under_a_half_pasted_url(tmp_path):
    """loadMe() reloads the card after every credential change, and the /user
    panel has no drawer-state snapshot to fall back on -- so a re-render while a
    callback URL is being pasted would throw the paste away."""
    import shutil
    import subprocess

    from m365_copilot_openai_proxy.template_pkce import _USER_PKCE_JS

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for inline UI behavior tests")
    script = "\n".join(
        [
            "const assert=require('assert');",
            "let lang='zh';",
            "function t(k){return k}",
            "function esc(v){return String(v??'')}",
            "function authHeaders(){return {}}",
            "function loadMe(){}",
            "const box={dataset:{},innerHTML:''};",
            "global.document={getElementById:id=>id==='pkce-panel'?box:null};",
            _USER_PKCE_JS,
            "renderUserPkce({id:'acct_1',provider:'m365'});",
            "assert.ok(box.innerHTML.includes('pkce-cb-acct_1'),box.innerHTML);",
            "box.innerHTML='<!--being typed into-->';",
            "renderUserPkce({id:'acct_1',provider:'m365'});",
            "assert.strictEqual(box.innerHTML,'<!--being typed into-->','panel rebuilt');",
            # A real change must still re-render: new account, or new language.
            "renderUserPkce({id:'acct_2',provider:'m365'});",
            "assert.ok(box.innerHTML.includes('pkce-cb-acct_2'),box.innerHTML);",
            "box.innerHTML='stale';lang='en';",
            "renderUserPkce({id:'acct_2',provider:'m365'});",
            "assert.ok(box.innerHTML.includes('pkce-cb-acct_2'),'language switch left it stale');",
            # No account, or a consumer one: a hint, never a sign-in button.
            "renderUserPkce(null);",
            "assert.ok(box.innerHTML.includes('pkce_no_account'),box.innerHTML);",
            "renderUserPkce({id:'acct_3',provider:'consumer'});",
            "assert.ok(box.innerHTML.includes('pkce_no_account'),box.innerHTML);",
        ]
    )
    path = tmp_path / "user-pkce-panel.js"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")

    assert result.returncode == 0, (result.stderr or "") + (result.stdout or "")


# --- the keepalive that used to require a browser ------------------------


def test_media_keepalive_mints_from_the_rt_instead_of_launching_chromium(admin, aad):
    app, _client, account = admin
    store = app.state.account_store
    _bind_rt(app, account.id)
    store.set_cookies(account.id, [{"name": "ESTSAUTH", "domain": ".login.microsoftonline.com"}])
    store.set_media_seed_url(account.id, "https://m365.cloud.microsoft/chat/conversation/x")
    scheduler = app.state.refresh_scheduler
    launched = []
    scheduler._inject_cookies_one = lambda *a, **k: launched.append(a)
    aad.response = _Response(200, {"access_token": _jwt(aud="https://ic3.teams.office.com")})

    asyncio.run(
        scheduler.ensure_media_fresh(account.id, "https://teams.microsoft.com/x/media/1")
    )

    assert launched == []  # no Chromium, no cookie replay
    assert store.get(account.id).media_auth_token


def test_media_keepalive_still_falls_back_to_the_seed_capture_without_an_rt(admin, aad):
    """Accounts that only have a browser session must keep working unchanged."""
    app, _client, account = admin
    store = app.state.account_store
    store.set_cookies(account.id, [{"name": "ESTSAUTH", "domain": ".login.microsoftonline.com"}])
    store.set_media_seed_url(account.id, "https://m365.cloud.microsoft/chat/conversation/x")
    scheduler = app.state.refresh_scheduler
    launched = []

    async def _fake_inject(account_id, cookies, allow_nudge=False):
        launched.append(account_id)

    scheduler._inject_cookies_one = _fake_inject

    asyncio.run(
        scheduler.ensure_media_fresh(account.id, "https://teams.microsoft.com/x/media/1")
    )

    assert launched == [account.id]
    assert aad.calls == []


def test_media_keepalive_does_nothing_while_the_token_is_fresh(admin, aad):
    app, _client, account = admin
    store = app.state.account_store
    _bind_rt(app, account.id)
    store.set_media_auth_token(account.id, _jwt(aud="https://ic3.teams.office.com"))

    asyncio.run(
        asyncio.wait_for(
            app.state.refresh_scheduler.ensure_media_fresh(
                account.id, "https://teams.microsoft.com/x/media/1"
            ),
            5,
        )
    )

    assert aad.calls == []


# --- the drawer the login panel lives in --------------------------------


def test_the_drawer_survives_the_reload_that_used_to_close_it(tmp_path):
    """A table rebuild must not collapse the drawer or eat what is in it.

    The accounts table is re-rendered by the 30s poll and by every mutation that
    ends in loadAccounts(), and the drawer's open state, the callback URL being
    pasted into it and the result message all live only in that markup. So
    "start sign-in" -> switch to the Microsoft tab -> come back found the drawer
    shut (the operator's report), and pkceComplete's own reload wiped the
    "signed in" line it had just written, leaving the sign-in with no visible
    outcome.
    """
    import shutil
    import subprocess

    from m365_copilot_openai_proxy.template_admin_accounts import _ADMIN_ACCOUNTS_JS

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for inline UI behavior tests")
    script = "\n".join(
        [
            "const assert=require('assert');",
            "let focused='',caret=null;",
            "const els={};",
            "function El(id){return {id:id,style:{},value:'',innerHTML:'',"
            "selectionStart:null,selectionEnd:null,"
            "focus(){focused=this.id},setSelectionRange(a,b){caret=[a,b]}}}",
            "global.localStorage={getItem:()=>null,setItem(){}};",
            "global.document={getElementById:id=>els[id]||null,activeElement:null};",
            _ADMIN_ACCOUNTS_JS,
            "__accounts=[{id:'a1'},{id:'a2'}];",
            # a1: drawer open, callback URL half-pasted, caret in it, message shown
            "['atok-a1','pkce-cb-a1','pkce-msg-a1','atok-a2'].forEach(i=>els[i]=El(i));",
            "els['atok-a1'].style.display='table-row';",
            "els['atok-a2'].style.display='none';",
            "els['pkce-cb-a1'].value='https://login.microsoftonline.com/x?code=abc';",
            "els['pkce-cb-a1'].selectionStart=7;els['pkce-cb-a1'].selectionEnd=7;",
            "els['pkce-msg-a1'].innerHTML='signed in, <a href=\"#\">open manually</a>';",
            "els['pkce-msg-a1'].style.color='var(--muted)';",
            "global.document.activeElement=els['pkce-cb-a1'];",
            "const st=_grabDrawerState({contains:()=>true});",
            # the re-render: fresh elements, drawer closed, inputs empty
            "['atok-a1','pkce-cb-a1','pkce-msg-a1','atok-a2'].forEach(i=>els[i]=El(i));",
            "els['atok-a1'].style.display='none';els['atok-a2'].style.display='none';",
            "_putDrawerState(st);",
            "assert.strictEqual(els['atok-a1'].style.display,'table-row','open drawer closed');",
            "assert.strictEqual(els['pkce-cb-a1'].value,"
            "'https://login.microsoftonline.com/x?code=abc','pasted URL lost');",
            "assert.ok(els['pkce-msg-a1'].innerHTML.includes('open manually'),'message lost');",
            "assert.strictEqual(els['pkce-msg-a1'].style.color,'var(--muted)');",
            "assert.strictEqual(els['atok-a2'].style.display,'none','closed drawer sprang open');",
            "assert.strictEqual(focused,'pkce-cb-a1','focus lost mid-paste');",
            "assert.deepStrictEqual(caret,[7,7],'caret lost mid-paste');",
        ]
    )
    path = tmp_path / "drawer-state.js"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [node, str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )

    assert result.returncode == 0, (result.stderr or "") + (result.stdout or "")


def test_the_preserved_ids_are_the_ids_the_markup_emits():
    """Guards the drift that would silently un-fix the reload: the state helpers
    address rows by id, so a renamed id in the markup makes them no-ops."""
    from m365_copilot_openai_proxy.template_admin_accounts import _ADMIN_ACCOUNTS_JS
    from m365_copilot_openai_proxy.template_pkce import _ADMIN_PKCE_JS

    markup = _ADMIN_ACCOUNTS_JS + _ADMIN_PKCE_JS
    for prefix in ("atok-", "atok-val-", "atok-msg-", "pkce-cb-", "pkce-msg-"):
        assert any(
            f"id=\"{prefix}'+{var}" in markup for var in ("a.id", "id")
        ), f"{prefix} is preserved on reload but no longer rendered under that id"
