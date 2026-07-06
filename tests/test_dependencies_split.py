from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI

from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.dependencies import create_api_dependencies


def test_create_api_dependencies_returns_settings_and_client_dependencies(tmp_path):
    app = FastAPI()
    settings = Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")
    sentinel_client = object()

    app.state.settings = settings
    app.state.copilot_client_factory = lambda: sentinel_client

    get_settings, get_copilot_client = create_api_dependencies(app)

    request = SimpleNamespace(state=SimpleNamespace())

    assert get_settings() is settings
    assert get_copilot_client(request) is sentinel_client
