from __future__ import annotations

from fastapi import FastAPI

from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.state_init import init_app_state


def test_init_app_state_populates_runtime_state_and_stores(tmp_path):
    app = FastAPI()
    settings = Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")
    sentinel_client = object()

    init_app_state(app, settings, lambda: sentinel_client)

    assert app.state.settings is settings
    assert app.state.account_store.list() == []
    assert app.state.key_store.list() == []
    assert app.state.runtime_settings["model_alias"] == "m365-copilot"
    assert app.state.model_alias == "m365-copilot"
    assert app.state.call_log == []
    assert app.state.captured_payloads == []
    assert app.state.last_request_time == 0
    assert app.state.copilot_client_factory() is sentinel_client
