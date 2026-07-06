from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from .config import Settings
from .admin_auth import create_admin_auth
from .auth_middleware import register_auth_middleware
from .dependencies import create_api_dependencies
from .error_handlers import register_error_handlers
from .route_registry import register_app_routes
from .state_init import init_app_state
from .startup_warnings import report_startup_warnings
from .substrate_client import SubstrateCopilotClient




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

    register_app_routes(app, admin_auth, resolved_settings, get_settings, get_copilot_client)

    return app

