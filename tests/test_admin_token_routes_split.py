from __future__ import annotations

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_admin_token import register_admin_token_routes


def test_admin_token_routes_gate_shared_cdp_endpoints(tmp_path):
    disabled = create_app(Settings(TOKEN_DIR=str(tmp_path / "off"), API_KEY="admin-key"))
    enabled = create_app(Settings(TOKEN_DIR=str(tmp_path / "on"), API_KEY="admin-key", ENABLE_ADMIN_CDP=True))

    off_paths = {route.path for route in disabled.routes}
    on_paths = {route.path for route in enabled.routes}

    assert callable(register_admin_token_routes)
    # Token status/update endpoints do not depend on the shared 9222 browser.
    for path in ("/admin/token/status", "/admin/token/auto-refresh-toggle", "/admin/token/update"):
        assert path in off_paths
        assert path in on_paths
    # These four talk to the shared admin CDP and are absent by default.
    gated = {
        "/admin/token/auto-capture",
        "/admin/cookie/inject",
        "/admin/chromium/login-status",
        "/admin/chromium/logout",
    }
    assert not (gated & off_paths)
    assert gated <= on_paths
