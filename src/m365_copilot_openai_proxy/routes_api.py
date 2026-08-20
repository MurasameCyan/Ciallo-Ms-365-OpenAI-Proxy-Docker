from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from .config import Settings
from .routes_api_chat import register_chat_routes
from .routes_api_messages import register_messages_routes
from .routes_api_responses import register_responses_routes
from .substrate_client import SubstrateCopilotClient


def register_api_routes(
    app: FastAPI,
    get_settings: Callable[[], Settings],
    get_copilot_client: Callable[..., SubstrateCopilotClient],
) -> None:
    register_chat_routes(app, get_settings, get_copilot_client)
    register_responses_routes(app, get_settings, get_copilot_client)
    register_messages_routes(app, get_settings, get_copilot_client)
