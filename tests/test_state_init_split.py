from __future__ import annotations

import json

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
    assert app.state.usage_store.summary()["calls_total"] == 0
    assert app.state.usage_store.path == tmp_path / "usage_stats.json"
    assert app.state.captured_payloads == []
    assert app.state.last_request_time == 0
    assert app.state.copilot_client_factory() is sentinel_client


def test_init_app_state_exposes_loaded_consumer_mode_options(tmp_path):
    expected = [
        {"model": "custom-consumer", "mode": "reasoning", "status": "experimental"},
    ]
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"consumer_mode_options": expected}),
        encoding="utf-8",
    )
    app = FastAPI()

    init_app_state(app, Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    assert app.state.runtime_settings["consumer_mode_options"] == expected
    assert app.state.consumer_mode_options == expected
