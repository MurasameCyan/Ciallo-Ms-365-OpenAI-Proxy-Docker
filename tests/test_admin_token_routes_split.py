from __future__ import annotations

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_admin_token import register_admin_token_routes


def test_admin_token_routes_are_registered_by_token_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_admin_token_routes)
    assert "/admin/token/status" in paths
    assert "/admin/token/auto-refresh-toggle" in paths
    assert "/admin/token/update" in paths
    assert "/admin/token/auto-capture" in paths
    assert "/admin/cookie/inject" in paths
    assert "/admin/chromium/login-status" in paths
    assert "/admin/chromium/logout" in paths
