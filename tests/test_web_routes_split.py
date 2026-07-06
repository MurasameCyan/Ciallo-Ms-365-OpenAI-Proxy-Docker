from __future__ import annotations

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_web import register_web_routes


def test_web_routes_are_registered_by_web_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_web_routes)
    assert "/" in paths
    assert "/admin" in paths
    assert "/admin/login" in paths
    assert "/admin/logout" in paths
    assert "/favicon.ico" in paths
    assert "/healthz" in paths
