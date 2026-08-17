from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from .account_store import AccountStore
from .call_log_store import load_call_log
from .config import Settings
from .history_index import HistoryDigestIndex
from .media_proxy_events import init_media_proxy_events
from .key_store import KeyStore
from .login_guard import LoginRateLimiter
from .metrics_store import init_metrics_store
from .refresh_scheduler import RefreshScheduler
from .runtime_flags import set_flags as _set_log_flags
from .runtime_settings import _read_runtime_settings, apply_proxy_env
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


def _resolve_media_proxy_secret(settings: Settings, token_dir: str) -> str:
    """Return the HMAC secret used to sign media-proxy URLs.

    Prefer the configured API_KEY / ADMIN_PASSWORD so behaviour is unchanged for
    configured deployments. When neither is set, generate a random secret once
    and persist it under the token dir (0600) instead of falling back to a
    public, guessable constant. Persisting keeps signatures valid across
    restarts; media URLs also carry a short TTL so stale signatures expire fast.
    """
    configured = settings.api_key or settings.admin_password
    if configured:
        return configured
    secret_path = Path(token_dir) / "media_proxy_secret"
    try:
        existing = secret_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except (FileNotFoundError, OSError):
        pass
    generated = secrets.token_urlsafe(32)
    try:
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        secret_path.write_text(generated, encoding="utf-8")
        try:
            secret_path.chmod(0o600)
        except OSError:
            pass
    except OSError:
        # Persistence is best-effort; a per-process random secret still beats a
        # public constant even if it cannot be written to disk.
        pass
    return generated


def init_app_state(
    app: FastAPI,
    settings: Settings,
    copilot_client_factory: Callable[..., SubstrateCopilotClient] | None = None,
) -> None:
    init_token_dir(settings.token_dir)
    app.state.settings = settings
    app.state.token_store = AccessTokenStore(settings.access_token)
    app.state.session_store = PersistentSessionStore(
        persist_path=Path(settings.token_dir) / "sessions.json",
        # Coalesce disk writes: one write rewrites every session, and every turn
        # of every conversation triggers one. Two seconds of turn bookkeeping is
        # the only thing a hard kill can lose (a graceful stop flushes).
        flush_interval=2.0,
    )
    # Exact-history -> session map, so two conversations that open with the same
    # text (an agent framework's templated first message) keep separate upstream
    # threads instead of resetting each other. In-memory only: on restart the
    # legacy first-message key still finds the session sessions.json restored.
    app.state.history_index = HistoryDigestIndex()
    app.state.account_store = AccountStore(
        persist_path=Path(settings.token_dir) / "accounts.json"
    )
    app.state.key_store = KeyStore(
        persist_path=Path(settings.token_dir) / "keys.json"
    )
    # Per-IP failed-login throttle for the /user self-service login (mirrors the
    # admin login lockout). Shared instance so /user/login and /user/repassword
    # count against the same window.
    app.state.user_login_limiter = LoginRateLimiter()
    app.state.refresh_scheduler = RefreshScheduler(
        app.state.account_store,
        profile_root=Path(settings.token_dir) / "profiles",
    )
    runtime_settings = _read_runtime_settings(
        settings.token_dir,
        env_defaults={
            "user_log_verbose": settings.log_user_verbose,
            "user_log_errors": settings.log_user_errors,
            "suppress_access_log": settings.suppress_access_log,
        },
    )
    app.state.call_log_limit = runtime_settings["call_log_limit"]
    app.state.call_log_path = Path(settings.token_dir) / "call_log.json"
    app.state.call_log: list[dict] = load_call_log(app.state.call_log_path, app.state.call_log_limit)
    app.state.call_log_version = len(app.state.call_log)
    app.state.captured_payloads: list[dict] = []
    app.state.capture_payload_version = 0
    init_media_proxy_events(app.state)
    init_metrics_store(app.state, Path(settings.token_dir) / "metrics_history.json")
    app.state.runtime_settings = runtime_settings
    # Publish the proxy before anything opens an upstream connection. Also pins
    # localhost into NO_PROXY when no proxy is set, so a deployment-level
    # HTTPS_PROXY can never swallow the local CDP traffic.
    apply_proxy_env(runtime_settings["proxy_url"])
    app.state.model_alias = runtime_settings["model_alias"]
    app.state.time_zone = runtime_settings["time_zone"]
    app.state.auto_refresh_enabled = runtime_settings["auto_refresh"]
    app.state.media_proxy_secret = _resolve_media_proxy_secret(settings, settings.token_dir)
    app.state.media_proxy_timeout = 60.0
    app.state.refresh_before_seconds = runtime_settings["refresh_before_seconds"]
    app.state.cdp_port = runtime_settings["cdp_port"]
    app.state.account_cdp_port_base = runtime_settings["account_cdp_port_base"]
    app.state.account_store.set_cdp_port_base(app.state.account_cdp_port_base)
    app.state.log_level = runtime_settings["log_level"]
    app.state.run_permission = runtime_settings["run_permission"]
    app.state.tone_options = runtime_settings["tone_options"]
    app.state.consumer_mode_options = runtime_settings["consumer_mode_options"]
    # User/account log toggles: sync process-wide flags from the resolved settings.
    app.state.user_log_verbose = runtime_settings["user_log_verbose"]
    app.state.user_log_errors = runtime_settings["user_log_errors"]
    app.state.suppress_access_log = runtime_settings["suppress_access_log"]
    _set_log_flags(
        verbose=runtime_settings["user_log_verbose"],
        errors=runtime_settings["user_log_errors"],
        suppress_access_log=runtime_settings["suppress_access_log"],
    )
    # Whether the shared admin CDP (port 9222) and its dependent endpoints are on.
    # Pure .env: pool deployments leave it off and drive per-account Chromium.
    app.state.admin_cdp_enabled = bool(settings.enable_admin_cdp)
    logging.getLogger().setLevel(app.state.log_level)
    app.state.last_request_time = 0
    app.state.idle_timeout_minutes = runtime_settings["idle_timeout_minutes"]
    app.state.ws_idle_timeout_minutes = runtime_settings["ws_idle_timeout_minutes"]
    app.state.keepalive_check_minutes = runtime_settings["keepalive_check_minutes"]
    app.state.cookie_keepalive_before_hours = runtime_settings["cookie_keepalive_before_hours"]
    app.state.refresh_scheduler.set_keepalive_params(
        check_interval_seconds=runtime_settings["keepalive_check_minutes"] * 60,
        cookie_before_seconds=runtime_settings["cookie_keepalive_before_hours"] * 3600,
    )
    app.state.username = read_username()
    app.state.current_tone = read_tone() or "Magic"
    app.state.tool_prompt = read_tool_prompt()
    app.state.system_prompt = read_system_prompt()
    app.state.copilot_client_factory = copilot_client_factory or (
        lambda token=None, tone=None, tool_prompt=None, time_zone=None, idle_timeout=None: SubstrateCopilotClient(
            token if token is not None else app.state.token_store.get(),
            time_zone if time_zone is not None else getattr(app.state, "time_zone", "Asia/Shanghai"),
            tone if tone is not None else getattr(app.state, "current_tone", "Magic"),
            tool_prompt if tool_prompt is not None else getattr(app.state, "tool_prompt", ""),
            idle_timeout=idle_timeout,
        )
    )
