from __future__ import annotations

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.route_registry import register_app_routes


def test_route_registry_registers_all_app_route_groups(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    paths = {route.path for route in app.routes}

    assert callable(register_app_routes)
    assert "/admin/login" in paths
    assert "/admin/summary" in paths
    assert "/admin/stats" in paths
    assert "/admin/tone" in paths
    assert "/admin/keys" in paths
    assert "/user/me" in paths
    assert "/v1/models" in paths
