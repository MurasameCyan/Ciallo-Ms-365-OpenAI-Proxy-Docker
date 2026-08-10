from __future__ import annotations

import logging

from m365_copilot_openai_proxy import cli, runtime_flags


def _record(msg: str) -> logging.LogRecord:
    # Mimic a uvicorn.access record: the formatted message is the full line.
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, msg, None, None)


def _line(method: str, path: str, status: int) -> str:
    return f'172.21.0.1:43234 - "{method} {path} HTTP/1.1" {status} OK'


# --- _is_noisy_access_path -------------------------------------------------

def test_is_noisy_access_path_matches_root_favicon_and_health():
    assert cli._is_noisy_access_path("/") is True
    assert cli._is_noisy_access_path("/favicon.ico") is True
    assert cli._is_noisy_access_path("/healthz") is True


def test_is_noisy_access_path_matches_bare_and_nested_prefixes():
    # Bare /admin (no trailing slash) and nested admin/user paths are noisy.
    assert cli._is_noisy_access_path("/admin") is True
    assert cli._is_noisy_access_path("/admin/chromium/login-status") is True
    assert cli._is_noisy_access_path("/user") is True
    assert cli._is_noisy_access_path("/user/login") is True
    assert cli._is_noisy_access_path("/v1/m365-media?account_id=a&sig=b") is True


def test_is_noisy_access_path_keeps_real_api_traffic():
    # The chat API must never be classified as noise.
    assert cli._is_noisy_access_path("/v1/chat/completions") is False
    # A path that merely starts with the same letters as a prefix is not matched.
    assert cli._is_noisy_access_path("/administrator") is False
    assert cli._is_noisy_access_path("/users-export") is False


# --- _SuppressPollingAccess ------------------------------------------------

def test_filter_suppresses_successful_polling_when_flag_on():
    runtime_flags.set_flags(suppress_access_log=True)
    f = cli._SuppressPollingAccess()
    try:
        assert f.filter(_record(_line("GET", "/admin/chromium/login-status", 200))) is False
        assert f.filter(_record(_line("GET", "/", 200))) is False
        assert f.filter(_record(_line("GET", "/favicon.ico", 204))) is False
    finally:
        runtime_flags.set_flags(suppress_access_log=True)


def test_filter_keeps_real_api_and_errors_when_flag_on():
    runtime_flags.set_flags(suppress_access_log=True)
    f = cli._SuppressPollingAccess()
    try:
        # Real chat API traffic is always kept.
        assert f.filter(_record(_line("POST", "/v1/chat/completions", 200))) is True
        # 4xx/5xx on a noisy path is kept so failures stay visible.
        assert f.filter(_record(_line("GET", "/admin/chromium/login-status", 404))) is True
    finally:
        runtime_flags.set_flags(suppress_access_log=True)


def test_filter_keeps_successful_admin_mutations_when_flag_on():
    runtime_flags.set_flags(suppress_access_log=True)
    f = cli._SuppressPollingAccess()
    try:
        assert f.filter(
            _record(_line("POST", "/admin/accounts/acct_x/refresh", 200))
        ) is True
        assert f.filter(
            _record(_line("DELETE", "/admin/accounts/acct_x", 200))
        ) is True
    finally:
        runtime_flags.set_flags(suppress_access_log=True)


def test_filter_disabled_keeps_everything():
    runtime_flags.set_flags(suppress_access_log=False)
    f = cli._SuppressPollingAccess()
    try:
        assert f.filter(_record(_line("GET", "/admin/chromium/login-status", 200))) is True
        assert f.filter(_record(_line("GET", "/", 200))) is True
    finally:
        # Restore the default so state does not leak into other tests.
        runtime_flags.set_flags(suppress_access_log=True)
