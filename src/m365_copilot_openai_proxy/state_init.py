from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from .account_store import AccountStore
from .call_log_store import load_call_log
from .config import Settings
from .key_store import KeyStore
from .metrics_store import init_metrics_store
from .refresh_scheduler import RefreshScheduler
from .runtime_settings import _read_runtime_settings
from .session_store import PersistentSessionStore
from .substrate_client import SubstrateCopilotClient
from .token_store import (
    AccessTokenStore,
    init_token_dir,
    read_system_prompt,
    read_tone,
    read_tool_prompt,
    read_username,
)


def init_app_state(
    app: FastAPI,
    settings: Settings,
    copilot_client_factory: Callable[..., SubstrateCopilotClient] | None = None,
) -> None:
    init_token_dir(settings.token_dir)
    app.state.settings = settings
    app.state.token_store = AccessTokenStore(settings.access_token)
    app.state.session_store = PersistentSessionStore(
        persist_path=Path(settings.token_dir) / "sessions.json"
    )
    app.state.account_store = AccountStore(
        persist_path=Path(settings.token_dir) / "accounts.json"
    )
    app.state.key_store = KeyStore(
        persist_path=Path(settings.token_dir) / "keys.json"
    )
    app.state.refresh_scheduler = RefreshScheduler(
        app.state.account_store,
        profile_root=Path(settings.token_dir) / "profiles",
    )
    runtime_settings = _read_runtime_settings(settings.token_dir)
    app.state.call_log_limit = runtime_settings["call_log_limit"]
    app.state.call_log_path = Path(settings.token_dir) / "call_log.json"
    app.state.call_log: list[dict] = load_call_log(app.state.call_log_path, app.state.call_log_limit)
    app.state.call_log_version = len(app.state.call_log)
    app.state.captured_payloads: list[dict] = []
    app.state.capture_payload_version = 0
    init_metrics_store(app.state, Path(settings.token_dir) / "metrics_history.json")
    app.state.runtime_settings = runtime_settings
    app.state.model_alias = runtime_settings["model_alias"]
    app.state.time_zone = runtime_settings["time_zone"]
    app.state.auto_refresh_enabled = runtime_settings["auto_refresh"]
    app.state.image_proxy_secret = settings.api_key or settings.admin_password or "m365-image-proxy"
    app.state.refresh_before_seconds = runtime_settings["refresh_before_seconds"]
    app.state.cdp_port = runtime_settings["cdp_port"]
    app.state.account_cdp_port_base = runtime_settings["account_cdp_port_base"]
    app.state.account_store.set_cdp_port_base(app.state.account_cdp_port_base)
    app.state.log_level = runtime_settings["log_level"]
    app.state.run_permission = runtime_settings["run_permission"]
    logging.getLogger().setLevel(app.state.log_level)
    app.state.last_request_time = 0
    app.state.idle_timeout_minutes = runtime_settings["idle_timeout_minutes"]
    app.state.username = read_username()
    app.state.current_tone = read_tone() or "Magic"
    app.state.tool_prompt = read_tool_prompt()
    app.state.system_prompt = read_system_prompt()
    app.state.copilot_client_factory = copilot_client_factory or (
        lambda token=None, tone=None, tool_prompt=None, time_zone=None: SubstrateCopilotClient(
            token if token is not None else app.state.token_store.get(),
            time_zone if time_zone is not None else getattr(app.state, "time_zone", "Asia/Shanghai"),
            tone if tone is not None else getattr(app.state, "current_tone", "Magic"),
            tool_prompt if tool_prompt is not None else getattr(app.state, "tool_prompt", ""),
        )
    )
