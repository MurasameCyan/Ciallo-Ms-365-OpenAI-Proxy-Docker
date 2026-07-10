from __future__ import annotations

from pathlib import Path


ENTRYPOINT = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text(encoding="utf-8")


def test_entrypoint_creates_profile_before_chowning_it():
    mkdir_index = ENTRYPOINT.index('mkdir -p "$CHROME_PROFILE"')
    chown_index = ENTRYPOINT.index('chown -R app:app "$CHROME_PROFILE"')

    assert mkdir_index < chown_index


def test_entrypoint_starts_chromium_without_pipeline_so_pid_is_browser():
    launch_block = ENTRYPOINT[ENTRYPOINT.index('"$CHROME_BIN" \\'):ENTRYPOINT.index('CHROME_PID=$!')]

    assert '| grep' not in launch_block
    assert 'CHROME_LOG="/tmp/chromium-cdp.log"' in ENTRYPOINT
    assert 'tail -n 80 "$CHROME_LOG"' in ENTRYPOINT


def test_entrypoint_checks_cdp_version_endpoint_for_readiness():
    assert 'http://localhost:$CDP_PORT/json/version' in ENTRYPOINT


def test_entrypoint_prefers_configured_or_full_chromium_browser_binary():
    # chromium-headless-shell fails the M365 SSO / CDP-bind refresh flow, so the
    # startup probe must honour an explicit CHROME_BIN and otherwise fall back to
    # full Chromium (matching the known-good v8 entrypoint).
    assert 'if [ -n "${CHROME_BIN:-}" ] && command -v "$CHROME_BIN"' in ENTRYPOINT
    assert 'chromium-headless-shell' not in ENTRYPOINT
    assert 'command -v chromium &> /dev/null' in ENTRYPOINT


def test_entrypoint_starts_startup_cdp_without_requiring_env_token():
    # Multi-tenant tokens live in accounts.json, not M365_ACCESS_TOKEN, so CDP
    # startup must NOT gate on that env var (it would keep auto-refresh off for
    # pool deployments). It should start on CHROME_BIN + AUTO_REFRESH alone.
    assert 'STARTUP_CDP="false"' in ENTRYPOINT
    assert 'if [ -n "$M365_ACCESS_TOKEN" ]; then' not in ENTRYPOINT
    assert 'if [ -n "$CHROME_BIN" ] && [ "$AUTO_REFRESH" = "true" ]; then' in ENTRYPOINT
    assert '[ "$STARTUP_CDP" = "true" ]' in ENTRYPOINT


def test_entrypoint_does_not_log_missing_global_token_hints():
    assert "M365_ACCESS_TOKEN is not set; skipping startup Chromium CDP." not in ENTRYPOINT
    assert "Chromium headless not started. Token auto-refresh disabled." not in ENTRYPOINT
    assert "WARNING: M365_ACCESS_TOKEN is not set." not in ENTRYPOINT
    assert "Please get a token via the Tampermonkey script" not in ENTRYPOINT


def test_entrypoint_uses_container_safe_headless_mode():
    launch_block = ENTRYPOINT[ENTRYPOINT.index('"$CHROME_BIN" \\'):ENTRYPOINT.index('CHROME_PID=$!')]

    assert '--headless \\' in launch_block
    assert '--headless=new' not in launch_block
    assert '--disable-software-rasterizer' not in launch_block
    assert '--crash-dumps-dir=' not in launch_block


def test_entrypoint_starts_chromium_on_blank_page_until_cdp_is_ready():
    launch_block = ENTRYPOINT[ENTRYPOINT.index('"$CHROME_BIN" \\'):ENTRYPOINT.index('CHROME_PID=$!')]

    assert '"about:blank" > "$CHROME_LOG" 2>&1 &' in launch_block
    assert 'm365.cloud.microsoft/chat" > "$CHROME_LOG"' not in launch_block
