from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Request

from .admin_auth import AdminAuth
from .config import Settings
from .routes_admin import register_admin_account_key_routes
from .routes_admin_debug import register_admin_debug_routes
from .routes_admin_modeltest import register_admin_model_test_routes
from .routes_admin_observability import register_admin_observability_routes
from .routes_admin_personalization import register_admin_personalization_routes
from .routes_admin_settings import register_admin_settings_routes
from .routes_admin_token import register_admin_token_routes
from .routes_api import register_api_routes
from .routes_media_proxy import register_media_proxy_routes
from .routes_pkce import register_pkce_routes
from .routes_sessions import register_session_routes
from .routes_user import register_user_routes
from .routes_web import register_web_routes
from .substrate_client import SubstrateCopilotClient
from .tone_options import TONE_OPTIONS, TONE_VALUES


def register_app_routes(
    app: FastAPI,
    admin_auth: AdminAuth,
    resolved_settings: Settings,
    get_settings: Callable[[], Settings],
    get_copilot_client: Callable[[Request], SubstrateCopilotClient],
) -> None:
    register_web_routes(
        app,
        admin_auth.admin_secret,
        admin_auth.admin_session_token,
        admin_auth.is_admin_authenticated,
        admin_auth.login_failures,
        admin_auth.login_rate_limit,
        admin_auth.login_lockout_sec,
        require_admin=admin_auth.require_admin,
    )

    register_admin_token_routes(app, admin_auth.require_admin, admin_cdp_enabled=bool(resolved_settings.enable_admin_cdp))

    register_admin_observability_routes(app, admin_auth.require_admin)

    register_admin_debug_routes(app, admin_auth.require_admin)

    register_admin_model_test_routes(app, admin_auth.require_admin, get_copilot_client)

    register_pkce_routes(app, admin_auth.require_admin)

    register_admin_settings_routes(app, admin_auth.require_admin, resolved_settings, TONE_OPTIONS, TONE_VALUES)

    register_admin_account_key_routes(app, admin_auth.require_admin, TONE_VALUES)

    register_admin_personalization_routes(app, admin_auth.require_admin)

    register_user_routes(app, resolved_settings, TONE_OPTIONS)

    register_session_routes(app, admin_auth.require_admin)

    register_media_proxy_routes(app)

    register_api_routes(app, get_settings, get_copilot_client)
