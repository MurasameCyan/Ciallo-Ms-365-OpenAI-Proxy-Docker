"""Outbound proxy setting: validation, env publication, and localhost exemption.

The load-bearing test here is test_websockets_resolver_*: it drives the real
websockets/urllib resolution rather than re-checking our own string handling,
because websockets>=15 defaults to proxy=True and would otherwise route the
local CDP control channel through an admin-set proxy.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from websockets.asyncio.client import get_proxy
from websockets.uri import parse_uri

from m365_copilot_openai_proxy import runtime_settings as rs
from m365_copilot_openai_proxy.refresh_chromium import chromium_proxy_args

_SRC = Path(__file__).resolve().parents[1] / "src" / "m365_copilot_openai_proxy"


@pytest.fixture
def clean_proxy_env(monkeypatch):
    """Isolate the proxy env vars and treat the process baseline as empty."""
    for name in rs._PROXY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setattr(rs, "_BASE_PROXY_ENV", dict.fromkeys(rs._PROXY_ENV_VARS, None))
    return monkeypatch


@pytest.mark.parametrize(
    "value",
    [
        "http://127.0.0.1:1080",
        "https://proxy.internal:8443",
        "socks5://127.0.0.1:1080",
        "socks5h://proxy.example.com:1080",
        "http://user:pass@proxy.example.com:3128",
    ],
)
def test_normalize_accepts_usable_proxy_urls(value):
    assert rs.normalize_proxy_url(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        "127.0.0.1:1080",                    # no scheme
        "ftp://127.0.0.1:1080",              # unsupported scheme
        "http://127.0.0.1",                  # no port: httpx/Chromium disagree on the default
        "http://127.0.0.1:1080/path",        # path is meaningless on a proxy
        "http://127.0.0.1:1080?x=1",
        "http://127.0.0.1:99999",            # port out of range
        "http://host with space:1080",
        "http://127.0.0.1:1080\n--evil",     # control char -> argv injection risk
        "http://:1080",                      # no host
    ],
)
def test_normalize_rejects_unusable_proxy_urls(value):
    assert rs.normalize_proxy_url(value) == ""


def test_apply_proxy_env_publishes_all_scheme_vars(clean_proxy_env):
    rs.apply_proxy_env("socks5h://127.0.0.1:1080")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        assert os.environ[name] == "socks5h://127.0.0.1:1080"
        # httpx reads the lowercase spellings; both must agree.
        assert os.environ[name.lower()] == "socks5h://127.0.0.1:1080"


def test_apply_proxy_env_always_pins_localhost_even_with_no_proxy(clean_proxy_env):
    rs.apply_proxy_env("")
    for host in ("localhost", "127.0.0.1", "::1"):
        assert host in os.environ["NO_PROXY"]
    assert os.environ["no_proxy"] == os.environ["NO_PROXY"]
    # No proxy configured => no proxy vars set at all.
    assert "HTTPS_PROXY" not in os.environ


def test_apply_proxy_env_preserves_deployment_no_proxy_entries(clean_proxy_env):
    clean_proxy_env.setattr(
        rs, "_BASE_PROXY_ENV", {**dict.fromkeys(rs._PROXY_ENV_VARS, None), "NO_PROXY": "corp.example.com"}
    )
    rs.apply_proxy_env("http://127.0.0.1:1080")
    assert "corp.example.com" in os.environ["NO_PROXY"]
    assert "127.0.0.1" in os.environ["NO_PROXY"]


def test_clearing_proxy_restores_deployment_env(clean_proxy_env):
    clean_proxy_env.setattr(
        rs,
        "_BASE_PROXY_ENV",
        {**dict.fromkeys(rs._PROXY_ENV_VARS, None), "HTTPS_PROXY": "http://deploy:8080"},
    )
    rs.apply_proxy_env("http://admin:1080")
    assert os.environ["HTTPS_PROXY"] == "http://admin:1080"
    # Clearing the admin setting must not erase the deployment's own proxy.
    rs.apply_proxy_env("")
    assert os.environ["HTTPS_PROXY"] == "http://deploy:8080"


def test_invalid_proxy_never_reaches_the_environment(clean_proxy_env):
    rs.apply_proxy_env("http://127.0.0.1:1080\n--proxy-server=evil:1")
    assert "HTTPS_PROXY" not in os.environ


def test_websockets_resolver_proxies_upstream_but_not_local_cdp(clean_proxy_env):
    """The regression guard: websockets>=15 resolves proxy=True through
    urllib, so an admin proxy must reach substrate while CDP stays direct."""
    rs.apply_proxy_env("socks5h://127.0.0.1:1080")
    assert get_proxy(parse_uri("wss://substrate.office.com/v1/chat")) == "socks5h://127.0.0.1:1080"
    assert get_proxy(parse_uri("ws://localhost:9222/devtools/page/AB")) is None
    assert get_proxy(parse_uri("ws://127.0.0.1:9322/devtools/page/AB")) is None


def test_httpx_bypasses_local_cdp_when_proxy_configured(clean_proxy_env):
    import httpx

    rs.apply_proxy_env("http://127.0.0.1:1080")
    client = httpx.Client(trust_env=True)
    try:
        transport = client._transport_for_url(httpx.URL("http://localhost:9222/json"))
        assert transport is client._transport, "local CDP must not go through the proxy transport"
    finally:
        client.close()


def test_chromium_proxy_args_bypass_loopback(clean_proxy_env):
    assert chromium_proxy_args() == []
    rs.apply_proxy_env("http://127.0.0.1:1080")
    args = chromium_proxy_args()
    assert "--proxy-server=http://127.0.0.1:1080" in args
    bypass = next(a for a in args if a.startswith("--proxy-bypass-list="))
    for host in ("localhost", "127.0.0.1"):
        assert host in bypass


@pytest.mark.parametrize(
    "configured,expected",
    [
        ("socks5h://127.0.0.1:1080", "socks5://127.0.0.1:1080"),
        ("socks4a://127.0.0.1:1080", "socks4://127.0.0.1:1080"),
        ("socks5://127.0.0.1:1080", "socks5://127.0.0.1:1080"),
        ("http://127.0.0.1:1080", "http://127.0.0.1:1080"),
    ],
)
def test_chromium_gets_a_scheme_it_can_parse(clean_proxy_env, configured, expected):
    # socks5h/socks4a are valid for httpx and websockets but Chromium rejects
    # them, which would silently leave the refresh browser without a proxy.
    rs.apply_proxy_env(configured)
    assert f"--proxy-server={expected}" in chromium_proxy_args()


def test_every_chromium_launch_site_passes_proxy_args():
    # A launch site that forgets these flags silently ignores the admin setting,
    # so pin all four rather than only the scheduler's.
    for name in ("refresh_scheduler.py", "refresh_cookie_inject.py", "refresh_image_fetch.py", "cli.py"):
        source = (_SRC / name).read_text(encoding="utf-8")
        assert "*chromium_proxy_args()," in source, f"{name} launches Chromium without the proxy flags"


def test_admin_save_publishes_proxy_and_rejects_a_bad_one(tmp_path, clean_proxy_env):
    """End-to-end wiring: the admin POST must reach the process environment."""
    from fastapi.testclient import TestClient

    from m365_copilot_openai_proxy.app import create_app
    from m365_copilot_openai_proxy.config import Settings

    client = TestClient(create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="")))

    ok = client.post("/admin/runtime-settings", json={"proxy_url": "socks5h://127.0.0.1:1080"})
    assert ok.status_code == 200
    assert ok.json()["settings"]["proxy_url"] == "socks5h://127.0.0.1:1080"
    assert os.environ["HTTPS_PROXY"] == "socks5h://127.0.0.1:1080"
    assert get_proxy(parse_uri("ws://127.0.0.1:9222/devtools/page/AB")) is None

    bad = client.post("/admin/runtime-settings", json={"proxy_url": "not-a-proxy"})
    assert bad.status_code == 400
    # A rejected save must leave the working proxy in place.
    assert os.environ["HTTPS_PROXY"] == "socks5h://127.0.0.1:1080"

    cleared = client.post("/admin/runtime-settings", json={"proxy_url": ""})
    assert cleared.status_code == 200
    assert "HTTPS_PROXY" not in os.environ


def test_startup_pins_localhost_even_without_a_configured_proxy(tmp_path, clean_proxy_env):
    from m365_copilot_openai_proxy.app import create_app
    from m365_copilot_openai_proxy.config import Settings

    create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="k"))

    assert "127.0.0.1" in os.environ["NO_PROXY"]


def test_proxy_setting_round_trips_through_persistence(tmp_path):
    rs._write_runtime_settings(str(tmp_path), {**rs._RUNTIME_SETTINGS_DEFAULTS, "proxy_url": "socks5h://h:9050"})
    assert rs._read_runtime_settings(str(tmp_path))["proxy_url"] == "socks5h://h:9050"
    # A corrupt persisted value must not resurrect on read.
    rs._write_runtime_settings(str(tmp_path), {**rs._RUNTIME_SETTINGS_DEFAULTS, "proxy_url": "not-a-proxy"})
    assert rs._read_runtime_settings(str(tmp_path))["proxy_url"] == ""
