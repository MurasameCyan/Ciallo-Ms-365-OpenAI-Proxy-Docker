"""Exercise the real OAuth form builder, not a replacement for _post_token."""
from __future__ import annotations

import asyncio
import base64
import json
import time
from urllib.parse import parse_qs

import httpx
import pytest

from m365_copilot_openai_proxy.account_store import AccountStore
from m365_copilot_openai_proxy import consumer_refresh_via_rt as rt


def _oauth_transport(monkeypatch, *, identity="matching"):
    captured = []

    def respond(request):
        form = parse_qs(request.content.decode())
        captured.append((request, form))
        body = {
            "access_token": "fresh-consumer-access-token",
            "refresh_token": "rotated-refresh-token-" + "x" * 40,
            "expires_in": 3600,
        }
        # The real MSA endpoint omits client_info unless explicitly requested.
        # Unconditionally including it hid the missing form field in prior tests.
        if form.get("client_info") == ["1"] and identity != "missing":
            body["client_info"] = base64.urlsafe_b64encode(json.dumps({
                "uid": "account-a" if identity == "matching" else "account-b",
                "utid": "tenant-a",
            }).encode()).decode().rstrip("=")
        return httpx.Response(200, json=body)

    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    return captured


def test_oauth_form_explicitly_requests_client_info(monkeypatch):
    captured = _oauth_transport(monkeypatch)

    asyncio.run(rt._post_token(
        client_id=rt.CONSUMER_CLIENT_ID,
        refresh_token="stored-refresh-token-" + "x" * 40,
        scope=rt.CONSUMER_CHATAI_SCOPE,
        proxy="",
    ))

    request, form = captured[0]
    assert form.get("client_info") == ["1"]
    assert form["client_id"] == [rt.CONSUMER_CLIENT_ID]
    assert form["grant_type"] == ["refresh_token"]
    assert form["scope"] == [rt.CONSUMER_CHATAI_SCOPE + " openid profile offline_access"]
    assert request.headers["Origin"] == "https://copilot.microsoft.com"


@pytest.mark.parametrize("identity", ["matching", "different", "missing"])
def test_full_http_exchange_keeps_subject_validation_and_persists_success(tmp_path, monkeypatch, identity):
    captured = _oauth_transport(monkeypatch, identity=identity)
    path = tmp_path / "accounts.json"
    accounts = AccountStore(persist_path=path)
    account = accounts.add(name="consumer-http")
    accounts.set_consumer_auth(
        account.id,
        [{"name": "__Host-MSAAUTHP", "value": "fixture-cookie", "domain": ".live.com"}],
        "previous-consumer-access-token",
        consumer_account_id="home:account-a.tenant-a",
        consumer_refresh_token="stored-refresh-token-" + "x" * 40,
        consumer_refresh_token_client_id=rt.CONSUMER_CLIENT_ID,
        consumer_refresh_token_scope=rt.CONSUMER_CHATAI_SCOPE,
    )

    refreshed = asyncio.run(rt.refresh_consumer_via_rt(accounts, account.id))

    assert refreshed is (identity == "matching")
    assert len(captured) == 1
    reopened = AccountStore(persist_path=path).get(account.id)
    if identity == "matching":
        assert reopened.consumer_token == "fresh-consumer-access-token"
        assert reopened.consumer_refresh_token == "rotated-refresh-token-" + "x" * 40
        assert reopened.consumer_token_expires_at > time.time() + 3500
        assert reopened.consumer_token not in path.read_text()
        assert reopened.consumer_refresh_token not in path.read_text()
    else:
        assert reopened.consumer_token == "previous-consumer-access-token"
        assert reopened.consumer_refresh_token == ""
        assert reopened.consumer_refresh_token_disabled_reason == "consumer_rt_subject_mismatch"
