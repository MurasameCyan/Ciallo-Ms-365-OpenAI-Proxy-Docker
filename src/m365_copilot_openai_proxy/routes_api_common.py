from __future__ import annotations

from fastapi import FastAPI, Request

from .config import Settings
from .key_store import ApiKey
from .runtime_settings import _RUN_PERMISSIONS


def request_model_alias(app: FastAPI, raw_request: Request, settings: Settings) -> str:
    """Resolve the model alias for a request: the key's own override wins, then
    the admin-configured global alias, then the settings default."""
    key_obj = getattr(raw_request.state, "api_key_obj", None)
    return getattr(key_obj, "model_alias", "") or getattr(app.state, "model_alias", settings.model_alias)


def effective_run_permission(app: FastAPI, k: ApiKey | None) -> str:
    """Resolve the run permission for a key, falling back to the global setting."""
    value = ((getattr(k, "run_permission", "") if k is not None else "") or "").strip()
    return value if value in _RUN_PERMISSIONS else getattr(app.state, "run_permission", "full")
