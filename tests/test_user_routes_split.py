from __future__ import annotations

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_user import register_user_routes


def test_user_routes_are_registered_by_user_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_user_routes)
    assert "/user/login" in paths
    assert "/user/me" in paths
    assert "/user/account/token" in paths
    assert "/user/account/cookies" in paths
    assert "/user/account/unbind" in paths
