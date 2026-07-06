from __future__ import annotations

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.auth_middleware import register_auth_middleware
from m365_copilot_openai_proxy.config import Settings


def test_auth_middleware_is_registered_by_auth_middleware_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    assert callable(register_auth_middleware)
    assert any("api_key_auth" in repr(middleware) for middleware in app.user_middleware)
