from __future__ import annotations

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_admin_settings import register_admin_settings_routes


def test_admin_settings_routes_are_registered_by_settings_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_admin_settings_routes)
    assert "/admin/tone" in paths
    assert "/admin/runtime-settings" in paths
    assert "/admin/tool-prompt" in paths
    assert "/admin/system-prompt" in paths
