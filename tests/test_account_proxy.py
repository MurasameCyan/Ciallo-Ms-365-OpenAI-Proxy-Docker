"""Per-account outbound proxy: field persistence, validation, and resolution.

The consumer Copilot path needs a different egress from M365 (measured
2026-08-12: a real container-side Firefox on the direct egress gets
`challenge method=None`, so consumer traffic has to leave through a proxy),
which a process-global HTTPS_PROXY cannot express.
"""

from __future__ import annotations

from m365_copilot_openai_proxy.account_store import Account, AccountStore


def test_account_defaults_to_no_proxy():
    assert Account().proxy_url == ""


def test_set_proxy_url_persists_across_reload(tmp_path):
    path = tmp_path / "accounts.json"
    store = AccountStore(persist_path=path)
    acc = store.add(name="a")
    assert store.set_proxy_url(acc.id, "socks5h://127.0.0.1:1080") is not None

    reloaded = AccountStore(persist_path=path)
    assert reloaded.get(acc.id).proxy_url == "socks5h://127.0.0.1:1080"


def test_set_proxy_url_rejects_unusable_value(tmp_path):
    store = AccountStore(persist_path=tmp_path / "accounts.json")
    acc = store.add(name="a")
    store.set_proxy_url(acc.id, "socks5h://127.0.0.1:1080")
    # No port: httpx and Chromium disagree on the default, so it is rejected
    # rather than normalised -- and a rejected write must not clear the old value.
    assert store.set_proxy_url(acc.id, "http://127.0.0.1") is None
    assert store.get(acc.id).proxy_url == "socks5h://127.0.0.1:1080"


def test_set_proxy_url_empty_clears(tmp_path):
    store = AccountStore(persist_path=tmp_path / "accounts.json")
    acc = store.add(name="a")
    store.set_proxy_url(acc.id, "socks5h://127.0.0.1:1080")
    assert store.set_proxy_url(acc.id, "") is not None
    assert store.get(acc.id).proxy_url == ""


def test_set_proxy_url_unknown_account():
    assert AccountStore().set_proxy_url("acct_nope", "http://h:1") is None


def test_resolve_returns_account_proxy_when_set():
    from m365_copilot_openai_proxy.account_store import resolve_account_proxy

    assert resolve_account_proxy(Account(proxy_url="socks5h://h:1080")) == "socks5h://h:1080"


def test_resolve_returns_empty_when_account_has_none():
    """Empty means "caller falls back to the proxy env vars", not "direct":
    apply_proxy_env has already published the global setting there."""
    from m365_copilot_openai_proxy.account_store import resolve_account_proxy

    assert resolve_account_proxy(Account()) == ""


def test_resolve_tolerates_none_account():
    from m365_copilot_openai_proxy.account_store import resolve_account_proxy

    assert resolve_account_proxy(None) == ""
