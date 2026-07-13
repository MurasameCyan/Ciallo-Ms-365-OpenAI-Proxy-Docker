from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.account_serializers import account_public, user_account_public
from m365_copilot_openai_proxy.account_store import AccountStore


def _sample_ls() -> dict:
    return {
        "msal.account.keys": "[\"uid.utid\"]",
        "uid.utid-login.windows.net-idtoken": "eyJhbGciOiJ...",
    }


def test_set_cookies_persists_local_storage_round_trip(tmp_path):
    # The MSAL localStorage seed must survive a save/reload so the persistent
    # profile can be re-seeded on every refresh (cookie-only profiles boot
    # NoAccountOnStart and dead-end on an interactive popup).
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    acc = store.add(name="user", token="", token_source="cdp")
    store.set_cookies(acc.id, [{"name": "ESTSAUTH", "value": "x", "domain": ".microsoft.com"}], _sample_ls())

    reloaded = AccountStore(persist_path=persist)
    got = reloaded.get(acc.id)
    assert got is not None
    assert got.local_storage == _sample_ls()


def test_set_cookies_without_local_storage_leaves_existing_untouched(tmp_path):
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    acc = store.add(name="user", token="", token_source="cdp")
    store.set_cookies(acc.id, [{"name": "ESTSAUTH", "value": "x", "domain": ".microsoft.com"}], _sample_ls())
    # A later cookie push without local_storage (e.g. GM cannot read it) must
    # not wipe the previously captured MSAL seed.
    store.set_cookies(acc.id, [{"name": "ESTSAUTH", "value": "y", "domain": ".microsoft.com"}], None)
    got = store.get(acc.id)
    assert got is not None
    assert got.local_storage == _sample_ls()


def test_public_serializers_never_expose_local_storage(tmp_path):
    # local_storage holds MSAL tokens; it must never leak through any public API
    # (admin or user). The serializers use an explicit field allowlist, so this
    # guards against a future accidental asdict-style exposure.
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    acc = store.add(name="user", token="tok", token_source="cdp")
    store.set_cookies(acc.id, [{"name": "ESTSAUTH", "value": "x", "domain": ".microsoft.com"}], _sample_ls())
    got = store.get(acc.id)

    assert "local_storage" not in account_public(got)
    assert "local_storage" not in (user_account_public(got) or {})


def test_media_seed_url_round_trip(tmp_path):
    # The media seed conversation URL must survive save/reload so the refresh
    # flow can revisit it on every refresh to re-capture media/designer auth.
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    acc = store.add(name="user", token="", token_source="cdp")
    seed = "https://m365.cloud.microsoft/chat/conversation/4479aead-9924-4cc1-a45c-6fca5b51402d"
    store.set_media_seed_url(acc.id, seed)

    reloaded = AccountStore(persist_path=persist)
    got = reloaded.get(acc.id)
    assert got is not None
    assert got.media_seed_url == seed


def test_public_serializers_expose_has_media_seed_not_url(tmp_path):
    # The raw seed URL is per-account config that can reveal a conversation id;
    # public APIs expose only a boolean presence flag, never the URL itself.
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    acc = store.add(name="user", token="tok", token_source="cdp")
    seed = "https://m365.cloud.microsoft/chat/conversation/4479aead-9924-4cc1-a45c-6fca5b51402d"
    store.set_media_seed_url(acc.id, seed)
    got = store.get(acc.id)

    pub = account_public(got)
    user_pub = user_account_public(got) or {}
    assert pub.get("has_media_seed") is True
    assert user_pub.get("has_media_seed") is True
    assert seed not in str(pub)
    assert seed not in str(user_pub)
    assert "media_seed_url" not in pub
    assert "media_seed_url" not in user_pub


def test_refresh_token_round_trip(tmp_path):
    # The OAuth2 refresh_token must survive save/reload so the scheduler can do
    # the plain-HTTP substrate exchange without a headless browser after restart.
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    acc = store.add(name="user", token="", token_source="manual")
    rt = "1.AT4A" + "x" * 200
    store.set_refresh_token(acc.id, rt)

    reloaded = AccountStore(persist_path=persist)
    got = reloaded.get(acc.id)
    assert got is not None
    assert got.refresh_token == rt


def test_public_serializers_expose_has_refresh_token_not_value(tmp_path):
    # The refresh_token is a long-lived high-value credential; public APIs expose
    # only a boolean presence flag, never the token value itself.
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    acc = store.add(name="user", token="tok", token_source="manual")
    rt = "1.AT4A" + "s3cr3t" * 40
    store.set_refresh_token(acc.id, rt)
    got = store.get(acc.id)

    pub = account_public(got)
    user_pub = user_account_public(got) or {}
    assert pub.get("has_refresh_token") is True
    assert user_pub.get("has_refresh_token") is True
    assert rt not in str(pub)
    assert rt not in str(user_pub)
    assert "refresh_token" not in pub
    assert "refresh_token" not in user_pub


def test_clear_credentials_wipes_refresh_token(tmp_path):
    # Clearing credentials (logout/unbind) must remove the refresh_token too, so
    # a wiped account cannot keep silently minting substrate tokens over HTTP.
    persist = tmp_path / "accounts.json"
    store = AccountStore(persist_path=persist)
    acc = store.add(name="user", token="tok", token_source="manual")
    store.set_refresh_token(acc.id, "1.AT4A" + "x" * 200)
    store.clear_credentials(acc.id)
    got = store.get(acc.id)
    assert got is not None
    assert got.refresh_token == ""
