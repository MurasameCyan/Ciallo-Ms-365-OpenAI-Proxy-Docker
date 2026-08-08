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
    seen = {}

    class _FakeBrowser:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def new_page(self):
            return _FakePage()

        async def cookies(self):
            return [{"name": "WLSSC", "value": "v", "domain": ".live.com"}]

    class _FakePage:
        async def goto(self, url, **kw):
            seen["url"] = url

        async def evaluate(self, script):
            return "minted-token"

    def factory(**kwargs):
        seen.update(kwargs)
        return _FakeBrowser()

    gate = cc.CamoufoxConsumerGate(tmp_path / "profile")
    auth = asyncio.run(gate._run(factory))

    assert seen["firefox_user_prefs"]["network.cookie.cookieBehavior"] == 0
    assert seen["persistent_context"] is True
    assert seen["user_data_dir"].endswith("profile")
    assert seen["url"] == cc.COPILOT_URL
    assert auth["access_token"] == "minted-token"
    assert auth["cookies"] == {"WLSSC": "v"}
    # MSAL mints without an X-UserIdentityType, so the caller keeps what it holds.
    assert auth["identity_type"] == ""


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
