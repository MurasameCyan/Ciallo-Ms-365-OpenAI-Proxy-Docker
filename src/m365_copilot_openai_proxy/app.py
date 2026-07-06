from __future__ import annotations

import logging
import os
import re
import secrets
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from .config import Settings
from .dependencies import create_api_dependencies
from .account_store import AccountStore
from .key_store import KeyStore
from .refresh_scheduler import RefreshScheduler
from .session_store import PersistentSessionStore
from .substrate_client import SubstrateCopilotClient
from .token_store import AccessTokenStore, read_username, decode_jwt_payload, init_token_dir, read_tone, read_tool_prompt, read_system_prompt
from .routes_admin import register_admin_account_key_routes
from .routes_api import register_api_routes
from .routes_admin_debug import register_admin_debug_routes
from .routes_admin_observability import register_admin_observability_routes
from .routes_admin_settings import register_admin_settings_routes
from .routes_admin_token import register_admin_token_routes
from .routes_user import register_user_routes
from .routes_web import register_web_routes
from .runtime_settings import _read_runtime_settings
from .call_log_store import load_call_log
from .metrics_store import init_metrics_store
from .session_helpers import _SESSION_ID_HEADER




def create_app(
    settings: Settings | None = None,
    copilot_client_factory: Callable[[], SubstrateCopilotClient] | None = None,
) -> FastAPI:
    app = FastAPI(title="Ciallo Ms-365 OpenAI Proxy")
    resolved_settings = settings or Settings()
    init_token_dir(resolved_settings.token_dir)
    app.state.settings = resolved_settings
    app.state.token_store = AccessTokenStore(resolved_settings.access_token)
    app.state.session_store = PersistentSessionStore(
        persist_path=Path(resolved_settings.token_dir) / "sessions.json"
    )  # Persist to mounted volume so conversations survive container restarts
    # Multi-tenant stores: account pool (each owns an isolated token + Chromium
    # profile/CDP port) and API key table (each key bound to one account, scheme B).
    app.state.account_store = AccountStore(
        persist_path=Path(resolved_settings.token_dir) / "accounts.json"
    )
    app.state.key_store = KeyStore(
        persist_path=Path(resolved_settings.token_dir) / "keys.json"
    )
    # On-demand token refresh scheduler: brings one account's Chromium up at a
    # time (serial), captures a fresh token via CDP, then tears it down. Keeps
    # peak memory close to single-tenant even with many accounts.
    app.state.refresh_scheduler = RefreshScheduler(
        app.state.account_store,
        profile_root=Path(resolved_settings.token_dir) / "profiles",
    )
    runtime_settings = _read_runtime_settings(resolved_settings.token_dir)
    app.state.call_log_limit = runtime_settings["call_log_limit"]
    app.state.call_log_path = Path(resolved_settings.token_dir) / "call_log.json"
    app.state.call_log: list[dict] = load_call_log(app.state.call_log_path, app.state.call_log_limit)  # API call log for web UI display
    app.state.captured_payloads: list[dict] = []  # Substrate chat payloads captured via get_token.js for mode comparison
    # Metrics time-series for the home dashboard trend chart.
    init_metrics_store(app.state, Path(resolved_settings.token_dir) / "metrics_history.json")
    app.state.runtime_settings = runtime_settings
    app.state.model_alias = runtime_settings["model_alias"]
    app.state.time_zone = runtime_settings["time_zone"]
    app.state.auto_refresh_enabled = runtime_settings["auto_refresh"]
    app.state.refresh_before_seconds = runtime_settings["refresh_before_seconds"]
    app.state.cdp_port = runtime_settings["cdp_port"]
    app.state.account_cdp_port_base = runtime_settings["account_cdp_port_base"]
    app.state.account_store.set_cdp_port_base(app.state.account_cdp_port_base)
    app.state.log_level = runtime_settings["log_level"]
    app.state.run_permission = runtime_settings["run_permission"]
    logging.getLogger().setLevel(app.state.log_level)
    app.state.last_request_time = 0  # 0 means never received any /v1/ request
    app.state.idle_timeout_minutes = runtime_settings["idle_timeout_minutes"]
    app.state.username = read_username()  # Restore persisted username (set via get_token.js push or CDP extraction)
    app.state.current_tone = read_tone() or "Magic"  # Restore persisted conversation tone (mode), default "Magic" (Auto)
    app.state.tool_prompt = read_tool_prompt()  # Restore persisted user-defined extra tool-call instruction
    app.state.system_prompt = read_system_prompt()  # Restore persisted system-level tool-call instruction override (empty = use default)
    if not resolved_settings.api_key:
        print("WARNING: API_KEY is not set. All /v1/ API endpoints are open without authentication. Set API_KEY in .env to secure your instance.")
    _admin_secret = resolved_settings.admin_password or resolved_settings.api_key
    if not _admin_secret:
        print("WARNING: Neither API_KEY nor ADMIN_PASSWORD is set. Web admin page is open without authentication. Set ADMIN_PASSWORD in .env to secure it.")

    # Generate a random admin session token instead of deterministic hash
    _admin_session_token: str | None = secrets.token_hex(32) if _admin_secret else None

    # Login rate limiting: track failed attempts by client IP
    _login_failures: dict[str, list[float]] = {}
    _LOGIN_RATE_LIMIT = 5       # max failures
    _LOGIN_LOCKOUT_SEC = 60.0   # lockout duration

    app.state.copilot_client_factory = copilot_client_factory or (
        lambda token=None, tone=None, tool_prompt=None, time_zone=None: SubstrateCopilotClient(
            token if token is not None else app.state.token_store.get(),
            time_zone if time_zone is not None else getattr(app.state, 'time_zone', 'Asia/Shanghai'),
            tone if tone is not None else getattr(app.state, 'current_tone', 'Magic'),
            tool_prompt if tool_prompt is not None else getattr(app.state, 'tool_prompt', ''),
        )
    )

    def _is_admin_authenticated(request: Request) -> bool:
        """Check if the request has a valid admin auth cookie."""
        if not _admin_secret:
            return True
        if _admin_session_token is None:
            return False
        cookie_val = request.cookies.get("admin_auth", "")
        return secrets.compare_digest(cookie_val, _admin_session_token)

    def _require_admin(request: Request):
        """Check admin cookie auth; return error response or None."""
        if _admin_secret and not _is_admin_authenticated(request):
            return JSONResponse({"error": {"message": "Admin authentication required", "type": "auth_error"}}, status_code=401)
        return None

    # CORS: use configurable origin whitelist (comma-separated ALLOWED_ORIGINS env var)
    _allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    _allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()] if _allowed_origins_raw else ["*"]
    _cors_is_wildcard = "*" in _allowed_origins

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", _SESSION_ID_HEADER],
        max_age=86400,
    )

    # API Key authentication middleware (runs after CORS)
    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):
        # Always handle preflight first
        if request.method == "OPTIONS":
            return await call_next(request)
        # Add CORS headers to all responses from this middleware
        def with_cors(resp):
            if _cors_is_wildcard:
                resp.headers["Access-Control-Allow-Origin"] = "*"
            else:
                origin = request.headers.get("origin", "")
                if origin in _allowed_origins:
                    resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = f"Content-Type, Authorization, {_SESSION_ID_HEADER}"
            resp.headers["Access-Control-Max-Age"] = "86400"
            return resp
        path = request.url.path
        # Track last request time for idle detection & on-demand refresh
        if path.startswith("/v1/"):
            app.state.last_request_time = time.time()

        # Public paths: admin page (own cookie auth), user page, health, and all
        # /admin/* + /user/* endpoints (each does its own cookie/key check).
        if path in ("/", "/admin", "/favicon.ico", "/healthz") or path.startswith("/admin/") or path.startswith("/user/"):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        match = re.match(r"^Bearer\s+(.+)$", auth, re.IGNORECASE)
        raw_key = match.group(1) if match else ""

        # Multi-tenant: resolve the API key -> ApiKey -> bound Account.
        key_obj = app.state.key_store.resolve(raw_key) if raw_key else None
        if key_obj is not None:
            if not key_obj.enabled:
                return with_cors(JSONResponse(
                    status_code=401,
                    content={"error": {"message": "API key is disabled", "type": "auth_error"}},
                ))
            account = app.state.account_store.get(key_obj.account_id) if key_obj.account_id else None
            # Bring the bound account's token up to date on demand (serial, one
            # Chromium at a time). No-op if the token is still valid.
            if account is not None and path.startswith("/v1/"):
                try:
                    ok = await app.state.refresh_scheduler.ensure_fresh(account.id)
                    account = app.state.account_store.get(account.id) or account
                    if not ok:
                        return with_cors(JSONResponse(
                            status_code=503,
                            content={"error": {"message": "On-demand token refresh failed. Cookie may be expired or CDP did not capture a fresh token; check container logs.", "type": "refresh_error"}},
                        ))
                except Exception as exc:
                    return with_cors(JSONResponse(
                        status_code=503,
                        content={"error": {"message": f"On-demand token refresh failed: {exc}", "type": "refresh_error"}},
                    ))
            request.state.api_key_obj = key_obj
            request.state.account = account
            return await call_next(request)

        # Legacy single API_KEY fallback (global admin key, no bound account).
        if resolved_settings.api_key and raw_key == resolved_settings.api_key:
            request.state.api_key_obj = None
            request.state.account = None
            return await call_next(request)

        # No auth configured at all (no keys registered and no legacy key): open.
        if not resolved_settings.api_key and not app.state.key_store.list():
            request.state.api_key_obj = None
            request.state.account = None
            return await call_next(request)

        return with_cors(JSONResponse(
            status_code=401,
            content={"error": {"message": "Invalid API key", "type": "auth_error"}},
        ))

    get_settings, get_copilot_client = create_api_dependencies(app)

    # Global exception handler — always return JSON (never HTML error pages)
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "internal_error"}},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"message": exc.detail, "type": "http_error"}},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    register_web_routes(
        app,
        _admin_secret,
        _admin_session_token,
        _is_admin_authenticated,
        _login_failures,
        _LOGIN_RATE_LIMIT,
        _LOGIN_LOCKOUT_SEC,
    )

    register_admin_token_routes(app, _require_admin)

    register_admin_observability_routes(app, _require_admin)

    register_admin_debug_routes(app, _require_admin)

    # Conversation tone (mode) options discovered from M365 Copilot's mode picker.
    # The `tone` field in the Substrate chat payload controls which model/mode is used.
    _TONE_OPTIONS = [
        {"value": "Magic", "label": "自动 / Auto", "label_zh": "自动", "label_en": "Auto"},
        {"value": "Chat", "label": "快速答复 / Fast", "label_zh": "快速答复", "label_en": "Fast"},
        {"value": "Reasoning", "label": "深度思考 / Think", "label_zh": "深度思考", "label_en": "Think"},
        {"value": "Gpt_5_5_Chat", "label": "GPT 5.5 快速响应", "label_zh": "GPT 5.5 快速响应", "label_en": "GPT 5.5 Fast"},
        {"value": "Gpt_5_5_Reasoning", "label": "GPT 5.5 深度思考", "label_zh": "GPT 5.5 深度思考", "label_en": "GPT 5.5 Think"},
        {"value": "Gpt_5_2_Chat", "label": "GPT 5.2 快速响应", "label_zh": "GPT 5.2 快速响应", "label_en": "GPT 5.2 Fast"},
        {"value": "Gpt_5_2_Reasoning", "label": "GPT 5.2 深度思考", "label_zh": "GPT 5.2 深度思考", "label_en": "GPT 5.2 Think"},
    ]
    _TONE_VALUES = {o["value"] for o in _TONE_OPTIONS}

    register_admin_settings_routes(app, _require_admin, resolved_settings, _TONE_OPTIONS, _TONE_VALUES)

    # ============================ Multi-tenant admin API ============================
    register_admin_account_key_routes(app, _require_admin, _TONE_VALUES)

    register_user_routes(app, resolved_settings, _TONE_OPTIONS)

    register_api_routes(app, get_settings, get_copilot_client)

    return app

