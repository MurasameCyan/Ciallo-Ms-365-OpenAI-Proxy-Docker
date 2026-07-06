from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from .config import Settings
from .admin_auth import create_admin_auth
from .auth_middleware import register_auth_middleware
from .dependencies import create_api_dependencies
from .error_handlers import register_error_handlers
from .state_init import init_app_state
from .startup_warnings import report_startup_warnings
from .substrate_client import SubstrateCopilotClient
from .tone_options import TONE_OPTIONS, TONE_VALUES
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
    report_startup_warnings(resolved_settings)
    admin_auth = create_admin_auth(resolved_settings)

    register_auth_middleware(app, resolved_settings)

    get_settings, get_copilot_client = create_api_dependencies(app)
    register_error_handlers(app)

    register_web_routes(
        app,
        admin_auth.admin_secret,
        admin_auth.admin_session_token,
        admin_auth.is_admin_authenticated,
        admin_auth.login_failures,
        admin_auth.login_rate_limit,
        admin_auth.login_lockout_sec,
    )

    register_admin_token_routes(app, admin_auth.require_admin)

    register_admin_observability_routes(app, admin_auth.require_admin)

    register_admin_debug_routes(app, admin_auth.require_admin)

    register_admin_settings_routes(app, admin_auth.require_admin, resolved_settings, TONE_OPTIONS, TONE_VALUES)

    # ============================ Multi-tenant admin API ============================
    register_admin_account_key_routes(app, admin_auth.require_admin, TONE_VALUES)

    register_user_routes(app, resolved_settings, TONE_OPTIONS)

    register_api_routes(app, get_settings, get_copilot_client)

    return app

