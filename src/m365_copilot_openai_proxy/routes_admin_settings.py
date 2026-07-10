from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import FastAPI, Request

from .config import Settings
from .response_helpers import _json_err
from .call_log_store import trim_call_log
from .runtime_settings import (
    _DEFAULT_MEDIA_PROXY_SUFFIXES,
    _LOG_LEVELS,
    _RUNTIME_SETTINGS_DEFAULTS,
    _RUN_PERMISSIONS,
    _write_runtime_settings,
    normalize_media_proxy_suffixes,
    normalize_tone_options,
)
from .token_store import write_system_prompt, write_tone, write_tool_prompt
from .translator import default_tool_system_prompt


def register_admin_settings_routes(
    app: FastAPI,
    require_admin: Callable[[Request], object | None],
    resolved_settings: Settings,
    tone_options: list[dict],
    tone_values: set[str],
) -> None:
    def _current_tone_options() -> list[dict]:
        # Read the live, admin-editable list; fall back to the built-in defaults.
        return list(getattr(app.state, "tone_options", None) or tone_options)

    @app.get("/admin/tone")
    async def get_tone(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        return {"tone": getattr(app.state, 'current_tone', 'Magic'), "options": _current_tone_options()}

    @app.post("/admin/tone")
    async def set_tone(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        body = await request.json()
        tone = (body.get("tone") or "").strip()
        allowed = {o["value"] for o in _current_tone_options()}
        if tone not in allowed:
            return _json_err(400, f"Invalid tone. Allowed: {', '.join(sorted(allowed))}")
        app.state.current_tone = tone
        write_tone(tone)
        return {"status": "ok", "tone": tone}

    @app.get("/admin/runtime-settings")
    async def get_runtime_settings(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        return {"settings": dict(getattr(app.state, "runtime_settings", _RUNTIME_SETTINGS_DEFAULTS))}

    @app.post("/admin/runtime-settings")
    async def set_runtime_settings(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        body = await request.json()
        current = dict(getattr(app.state, "runtime_settings", _RUNTIME_SETTINGS_DEFAULTS))
        def int_setting(name: str, minimum: int) -> int:
            try:
                return max(minimum, int(body.get(name, current[name])))
            except (TypeError, ValueError):
                return int(current[name])
        data = {
            "time_zone": str(body.get("time_zone", current["time_zone"])).strip() or _RUNTIME_SETTINGS_DEFAULTS["time_zone"],
            "model_alias": str(body.get("model_alias", current["model_alias"])).strip() or _RUNTIME_SETTINGS_DEFAULTS["model_alias"],
            "auto_refresh": bool(body.get("auto_refresh", current["auto_refresh"])),
            "refresh_before_seconds": int_setting("refresh_before_seconds", 0),
            "idle_timeout_minutes": int_setting("idle_timeout_minutes", 1),
            "ws_idle_timeout_minutes": int_setting("ws_idle_timeout_minutes", 1),
            "keepalive_check_minutes": int_setting("keepalive_check_minutes", 1),
            "cookie_keepalive_before_hours": int_setting("cookie_keepalive_before_hours", 1),
            "cdp_port": int_setting("cdp_port", 1),
            "account_cdp_port_base": int_setting("account_cdp_port_base", 1),
            "log_level": str(body.get("log_level", current["log_level"])).strip().upper() or _RUNTIME_SETTINGS_DEFAULTS["log_level"],
            "call_log_limit": int_setting("call_log_limit", 1),
            "run_permission": str(body.get("run_permission", current["run_permission"])).strip() or _RUNTIME_SETTINGS_DEFAULTS["run_permission"],
            "media_proxy_suffixes": normalize_media_proxy_suffixes(body.get("media_proxy_suffixes", current.get("media_proxy_suffixes"))) or list(_DEFAULT_MEDIA_PROXY_SUFFIXES),
            "media_proxy_ttl_seconds": int_setting("media_proxy_ttl_seconds", 60),
            "tone_options": normalize_tone_options(body.get("tone_options", current.get("tone_options"))),
        }
        if data["log_level"] not in _LOG_LEVELS:
            return _json_err(400, "Invalid log level")
        if data["run_permission"] not in _RUN_PERMISSIONS:
            return _json_err(400, "Invalid run permission")
        app.state.runtime_settings = data
        app.state.time_zone = data["time_zone"]
        app.state.model_alias = data["model_alias"]
        app.state.auto_refresh_enabled = data["auto_refresh"]
        app.state.refresh_before_seconds = data["refresh_before_seconds"]
        app.state.idle_timeout_minutes = data["idle_timeout_minutes"]
        app.state.ws_idle_timeout_minutes = data["ws_idle_timeout_minutes"]
        app.state.keepalive_check_minutes = data["keepalive_check_minutes"]
        app.state.cookie_keepalive_before_hours = data["cookie_keepalive_before_hours"]
        scheduler = getattr(app.state, "refresh_scheduler", None)
        if scheduler is not None:
            scheduler.set_keepalive_params(
                check_interval_seconds=data["keepalive_check_minutes"] * 60,
                cookie_before_seconds=data["cookie_keepalive_before_hours"] * 3600,
            )
        app.state.cdp_port = data["cdp_port"]
        app.state.account_cdp_port_base = data["account_cdp_port_base"]
        app.state.account_store.set_cdp_port_base(app.state.account_cdp_port_base)
        app.state.log_level = data["log_level"]
        app.state.tone_options = data["tone_options"]
        app.state.call_log_limit = data["call_log_limit"]
        trim_call_log(app.state)
        logging.getLogger().setLevel(app.state.log_level)
        _write_runtime_settings(resolved_settings.token_dir, data)
        return {"status": "ok", "settings": data}

    @app.get("/admin/tool-prompt")
    async def get_tool_prompt(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        return {"tool_prompt": getattr(app.state, 'tool_prompt', '')}

    @app.post("/admin/tool-prompt")
    async def set_tool_prompt(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        body = await request.json()
        prompt = body.get("tool_prompt")
        if not isinstance(prompt, str):
            return _json_err(400, "tool_prompt must be a string")
        prompt = prompt[:4000]  # cap length to avoid bloating every request
        app.state.tool_prompt = prompt
        write_tool_prompt(prompt)
        return {"status": "ok", "tool_prompt": prompt}

    @app.get("/admin/system-prompt")
    async def get_system_prompt(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        # Return the saved override plus the built-in default (for restore/initial fill).
        return {
            "system_prompt": getattr(app.state, 'system_prompt', ''),
            "default": default_tool_system_prompt(),
        }

    @app.post("/admin/system-prompt")
    async def set_system_prompt(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        body = await request.json()
        prompt = body.get("system_prompt")
        if not isinstance(prompt, str):
            return _json_err(400, "system_prompt must be a string")
        prompt = prompt[:8000]  # cap length to avoid bloating every request
        app.state.system_prompt = prompt
        write_system_prompt(prompt)
        return {"status": "ok", "system_prompt": prompt}
