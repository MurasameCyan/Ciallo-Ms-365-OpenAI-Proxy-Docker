"""The Camoufox consumer gate's non-browser surface.

Launching a real browser is out of scope for the suite, so these cover the parts
that decide *how* it launches -- proxy mapping, the load-bearing anti-partition
prefs, stale-lock cleanup -- plus the graceful degradation when the optional
browser package is missing.
"""

from __future__ import annotations

import asyncio

import pytest

from m365_copilot_openai_proxy import consumer_camoufox as cc
from m365_copilot_openai_proxy.consumer_client import ConsumerCopilotError


# ------------------------------------------------------------------ _proxy_option

def test_proxy_option_is_none_without_env(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    assert cc._proxy_option() is None


def test_proxy_option_passes_http_through(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    assert cc._proxy_option() == {"server": "http://127.0.0.1:7890"}


def test_proxy_option_maps_socks5h_to_socks5(monkeypatch):
    """socks5h is a curl convention Firefox cannot parse; its socks5 already
    resolves DNS remotely, so the mapping is an equivalence."""
    monkeypatch.setenv("HTTPS_PROXY", "socks5h://127.0.0.1:1080")
    assert cc._proxy_option() == {"server": "socks5://127.0.0.1:1080"}


def test_proxy_option_maps_socks4a_to_socks4(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "socks4a://host:1080")
    assert cc._proxy_option() == {"server": "socks4://host:1080"}


def test_proxy_option_reads_the_lowercase_variant(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("https_proxy", "http://proxy:8080")
    assert cc._proxy_option() == {"server": "http://proxy:8080"}


def test_proxy_option_prefers_explicit_override(monkeypatch):
    """A credential re-mint has to leave through the same egress the chat turns
    will use, or the minted cookies are scored against the wrong source IP.

    The socks5h -> socks5 mapping still applies: it is Firefox's parser that
    cannot read the curl spelling, so where the value came from is irrelevant.
    """
    monkeypatch.setenv("HTTPS_PROXY", "http://global:8080")
    assert cc._proxy_option("socks5h://acct:1080") == {"server": "socks5://acct:1080"}


def test_proxy_option_falls_back_to_env(monkeypatch):
    """"" is resolve_account_proxy's "no account proxy", which means "use the
    global setting the env already carries" -- not "go direct"."""
    monkeypatch.setenv("HTTPS_PROXY", "http://global:8080")
    assert cc._proxy_option("") == {"server": "http://global:8080"}


def test_proxy_option_none_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    assert cc._proxy_option("") is None


def test_proxy_option_splits_credentials_out_of_the_url(monkeypatch):
    """Firefox takes no userinfo in a proxy address and Playwright authenticates
    only from the separate fields, so an inline `user:pass@host` was read as the
    hostname: every launch through an authenticated account proxy died with
    NS_ERROR_PROXY_CONNECTION_REFUSED while curl_cffi accepted the same URL.
    """
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    assert cc._proxy_option("http://user:secret@203.0.113.7:3129") == {
        "server": "http://203.0.113.7:3129",
        "username": "user",
        "password": "secret",
    }


def test_proxy_option_decodes_percent_escaped_credentials(monkeypatch):
    """Percent-encoding is how a password containing @ or : survives the URL
    form, so the split has to undo it -- the browser gets the raw secret."""
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    assert cc._proxy_option("http://us%40er:p%3Ass%40word@host:8080") == {
        "server": "http://host:8080",
        "username": "us@er",
        "password": "p:ss@word",
    }


def test_proxy_option_splits_credentials_from_the_env_proxy_too(monkeypatch):
    """The global proxy reaches the browser through the same helper, so it has
    the same defect and needs the same split."""
    monkeypatch.setenv("HTTPS_PROXY", "socks5h://user:secret@host:1080")
    assert cc._proxy_option("") == {
        "server": "socks5://host:1080",
        "username": "user",
        "password": "secret",
    }


def test_proxy_option_keeps_a_bare_host_port_without_a_scheme(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    assert cc._proxy_option("user:secret@host:3129") == {
        "server": "host:3129",
        "username": "user",
        "password": "secret",
    }


# ---------------------------------------------------------------- profile handling

def test_clear_profile_locks_removes_a_stale_firefox_lock(tmp_path):
    """A killed browser leaves .parentlock behind, and the next launch then waits
    on it until Playwright's 180s timeout instead of failing fast."""
    (tmp_path / ".parentlock").write_text("stale")
    cc._clear_profile_locks(tmp_path)
    assert not (tmp_path / ".parentlock").exists()


def test_clear_profile_locks_is_a_no_op_on_a_clean_profile(tmp_path):
    cc._clear_profile_locks(tmp_path)  # must not raise


def test_clear_profile_locks_tolerates_a_missing_directory(tmp_path):
    cc._clear_profile_locks(tmp_path / "never-created")


def test_reset_consumer_profile_deletes_the_directory(tmp_path):
    profile = tmp_path / "acct-consumer"
    profile.mkdir()
    (profile / "cookies.sqlite").write_text("x")
    cc.reset_consumer_profile(profile)
    assert not profile.exists()


def test_reset_consumer_profile_tolerates_an_absent_directory(tmp_path):
    cc.reset_consumer_profile(tmp_path / "nope")


# ------------------------------------------------------------------ launch settings

def test_default_headless_is_virtual_on_linux(monkeypatch):
    """The image installs xvfb for this: true headless Firefox is a detectable
    signal, and evading detection is why this path uses Firefox at all."""
    monkeypatch.setattr(cc.sys, "platform", "linux")
    assert cc._default_headless() == "virtual"


def test_default_headless_is_plain_headless_off_linux(monkeypatch):
    """No xvfb on Windows/macOS, so "virtual" would simply fail to launch."""
    monkeypatch.setattr(cc.sys, "platform", "win32")
    assert cc._default_headless() is True


def test_explicit_headless_overrides_the_platform_default(tmp_path, monkeypatch):
    monkeypatch.setattr(cc.sys, "platform", "linux")
    assert cc.CamoufoxConsumerGate(tmp_path, headless=False)._headless is False


def test_partitioning_prefs_disable_total_cookie_protection():
    """Both halves are load-bearing: cookieBehavior 0 lets the MSAL SSO iframe
    read the MSA cookies, and partition.network_state False keeps the rest of the
    connection state unpartitioned with it. With either left at the Firefox
    default the page falls back to the sign-in wall and no token is minted."""
    assert cc._UNPARTITIONED_PREFS["network.cookie.cookieBehavior"] == 0
    assert cc._UNPARTITIONED_PREFS["privacy.partition.network_state"] is False


def test_gate_passes_the_prefs_and_profile_to_the_browser(tmp_path):
    """Guards the launch contract without a browser: a fake factory records what
    it was handed."""
    seen = {"events": []}

    class _FakeBrowser:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def new_page(self):
            return _FakePage()

        async def add_cookies(self, cookies):
            seen["events"].append("add_cookies")
            seen["seed_cookies"] = cookies

        async def cookies(self):
            return [
                {
                    "name": "WLSSC",
                    "value": "v",
                    "domain": ".live.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "None",
                    "expires": 2_000_000_000,
                },
                # Earned by this browser; must not travel to the HTTP client.
                {
                    "name": "__cf_bm",
                    "value": "x",
                    "domain": ".copilot.microsoft.com",
                    "path": "/",
                },
            ]

    class _FakePage:
        async def goto(self, url, **kw):
            seen["events"].append("goto")
            seen["url"] = url

        async def evaluate(self, script):
            if "consumer:clear-chat-token" in script:
                seen["events"].append("clear_token")
                return 1
            return {
                "access_token": "minted-token",
                "account_id": "home:account-a",
            }

        async def reload(self, **kw):
            seen["events"].append("reload")

    def factory(**kwargs):
        seen.update(kwargs)
        return _FakeBrowser()

    gate = cc.CamoufoxConsumerGate(
        tmp_path / "profile",
        seed_cookies=[
            {
                "name": "__Host-MSAAUTHP",
                "value": "seed",
                "domain": ".live.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "None",
                "expires": 2_000_000_000,
            },
            {
                "name": "__cf_bm",
                "value": "bad-seed",
                "domain": ".copilot.microsoft.com",
                "path": "/",
            },
            {
                "name": "ESTSAUTH",
                "value": "login-seed",
                "domain": ".login.microsoftonline.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "None",
            },
        ],
        previous_token="old-token",
    )
    auth = asyncio.run(gate._run(factory))

    assert seen["firefox_user_prefs"]["network.cookie.cookieBehavior"] == 0
    assert seen["persistent_context"] is True
    assert seen["user_data_dir"].endswith("profile")
    assert seen["url"] == cc.COPILOT_URL
    assert seen["events"][:2] == ["add_cookies", "goto"]
    assert seen["events"][2:4] == ["clear_token", "reload"]
    assert [cookie["name"] for cookie in seen["seed_cookies"]] == [
        "__Host-MSAAUTHP",
        "ESTSAUTH",
    ]
    assert auth["access_token"] == "minted-token"
    assert auth["account_id"] == "home:account-a"
    assert auth["cookies"] == [
        {
            "name": "WLSSC",
            "value": "v",
            "domain": ".live.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "None",
            "expires": 2_000_000_000,
        }
    ]
    # MSAL mints without an X-UserIdentityType, so the caller keeps what it holds.
    assert auth["identity_type"] == ""


def test_gate_passes_the_account_proxy_to_the_browser(tmp_path, monkeypatch):
    """The account's egress must reach the launch options, beating the env."""
    monkeypatch.setenv("HTTPS_PROXY", "http://global:8080")
    seen = {}

    class _FakeBrowser:
        async def __aenter__(self):
            # Nothing past the launch options is under test, and going further
            # would need the whole page/cookie fake for no added coverage.
            raise RuntimeError("stop after options are captured")

        async def __aexit__(self, *exc):
            return False

    def factory(**kwargs):
        seen.update(kwargs)
        return _FakeBrowser()

    gate = cc.CamoufoxConsumerGate(tmp_path / "p", proxy_url="socks5h://acct:1080")
    with pytest.raises(RuntimeError, match="stop after options"):
        asyncio.run(gate._run(factory))
    assert seen["proxy"] == {"server": "socks5://acct:1080"}


def test_cloudflare_cookies_are_dropped_before_changing_hands():
    """The consumer HTTP client impersonates firefox147 while this browser is
    Firefox 152, so a __cf_bm minted here would be replayed under a UA that did
    not earn it. _pick_cookies now drops them too; this path needs its own filter
    because it keeps full cookie records rather than flattening to name->value."""
    jar = [
        {"name": "WLSSC", "value": "v", "domain": ".live.com", "path": "/"},
        {"name": "__cf_bm", "value": "x", "domain": ".copilot.microsoft.com", "path": "/"},
        {"name": "__cflb", "value": "y", "domain": ".copilot.microsoft.com", "path": "/"},
        {"name": "cf_clearance", "value": "z", "domain": ".copilot.microsoft.com", "path": "/"},
    ]
    assert cc._drop_cloudflare_cookies(jar) == [jar[0]]


def test_cookie_records_map_userscript_no_restriction_to_playwright_none():
    records = cc._consumer_cookie_records(
        [
            {
                "name": "__Host-MSAAUTHP",
                "value": "seed",
                "domain": ".live.com",
                "path": "/",
                "secure": True,
                "sameSite": "No_restriction",
            }
        ]
    )

    assert records[0]["sameSite"] == "None"


def test_await_token_ignores_the_previous_cached_value(tmp_path):
    values = iter(
        [
            {"access_token": "old-token", "account_id": "home:account-a"},
            {"access_token": "new-token", "account_id": "home:account-a"},
        ]
    )

    class _FakePage:
        async def evaluate(self, script):
            return next(values)

    gate = cc.CamoufoxConsumerGate(
        tmp_path / "profile",
        previous_token="old-token",
        token_timeout=0.1,
        poll_interval=0,
    )

    assert asyncio.run(gate._await_token(_FakePage())) == (
        "new-token",
        "home:account-a",
    )


def test_run_raises_when_no_token_is_minted(tmp_path):
    """A lapsed MSA session loads the page fine but never mints; that has to be a
    clear error naming the one manual step that fixes it."""

    class _FakeBrowser:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def new_page(self):
            return _FakePage()

        async def cookies(self):
            return []

    class _FakePage:
        async def goto(self, url, **kw):
            return None

        async def evaluate(self, script):
            return ""

        async def reload(self, **kw):
            return None

    gate = cc.CamoufoxConsumerGate(tmp_path / "p", token_timeout=0.01, poll_interval=0.01)
    with pytest.raises(ConsumerCopilotError, match="interactive sign-in"):
        asyncio.run(gate._run(lambda **kw: _FakeBrowser()))


# ------------------------------------------------------------- optional dependency

def test_refresh_raises_camoufox_unavailable_without_the_package(tmp_path, monkeypatch):
    """The gate must name the fallback rather than surfacing a raw ImportError."""
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("camoufox"):
            raise ImportError("No module named 'camoufox'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    gate = cc.CamoufoxConsumerGate(tmp_path / "p")
    with pytest.raises(cc.CamoufoxUnavailable, match="userscript"):
        asyncio.run(gate._refresh())


def test_camoufox_unavailable_is_a_consumer_error():
    """So the /v1 error mapping already knows what to do with it."""
    assert issubclass(cc.CamoufoxUnavailable, ConsumerCopilotError)


def test_scheduler_builds_gate_with_account_proxy(tmp_path):
    """The scheduler is the only caller that knows which account is refreshing,
    so it is where the account's egress has to be read and handed over."""
    from m365_copilot_openai_proxy.account_store import AccountStore
    from m365_copilot_openai_proxy.refresh_scheduler import RefreshScheduler

    store = AccountStore(persist_path=tmp_path / "accounts.json")
    acc = store.add(name="c")
    store.set_consumer_auth(
        acc.id,
        [{"name": "_U", "value": "v", "domain": ".copilot.microsoft.com"}],
        "tok",
        consumer_account_id="home:abc",
    )
    assert store.set_proxy_url(acc.id, "socks5h://acct:1080") is not None

    sched = RefreshScheduler(store, profile_root=tmp_path / "profiles")
    gate = sched._build_consumer_gate(acc.id)
    assert gate._proxy_url == "socks5h://acct:1080"


def test_gate_lock_is_shared_per_profile(tmp_path):
    """Firefox allows one process per profile, so two refreshes for one account
    must serialise -- while different accounts stay independent."""

    async def check():
        a1 = cc._gate_lock(tmp_path / "a")
        a2 = cc._gate_lock(tmp_path / "a")
        b = cc._gate_lock(tmp_path / "b")
        return a1 is a2, a1 is b

    same, cross = asyncio.run(check())
    assert same is True
    assert cross is False
