from __future__ import annotations

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_api import register_api_routes


def test_v1_api_routes_are_registered_by_api_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_api_routes)
    assert "/v1/models" in paths
    assert "/v1/chat/completions" in paths
    assert "/v1/responses" in paths
    assert "/v1/messages" in paths
