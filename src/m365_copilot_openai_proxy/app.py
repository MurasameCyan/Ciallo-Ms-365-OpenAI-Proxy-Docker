from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .config import Settings
from .auth_middleware import register_auth_middleware
from .dependencies import create_api_dependencies
from .error_handlers import register_error_handlers
from .state_init import init_app_state
from .substrate_client import SubstrateCopilotClient
from .routes_admin import register_admin_account_key_routes
from .routes_api import register_api_routes
from .routes_admin_debug import register_admin_debug_routes
from .routes_admin_observability import register_admin_observability_routes
from .routes_admin_settings import register_admin_settings_routes
from .routes_admin_token import register_admin_token_routes
from .routes_user import register_user_routes
from .routes_web import register_web_routes




def create_app(
    settings: Settings | None = None,
    copilot_client_factory: Callable[..., SubstrateCopilotClient] | None = None,
) -> FastAPI:
    app = FastAPI(title="Ciallo Ms-365 OpenAI Proxy")
    resolved_settings = settings or Settings()
    init_app_state(app, resolved_settings, copilot_client_factory)
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

    register_auth_middleware(app, resolved_settings)

    get_settings, get_copilot_client = create_api_dependencies(app)
    register_error_handlers(app)

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

