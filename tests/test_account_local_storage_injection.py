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
