from __future__ import annotations

from fastapi import FastAPI, Request

from .config import Settings
from .key_store import ApiKey
from .runtime_settings import _RUN_PERMISSIONS
from .tone_options import TONE_OPTIONS as _BUILTIN_TONE_OPTIONS
from .tone_resolver import resolve_tone


def request_model_alias(app: FastAPI, raw_request: Request, settings: Settings) -> str:
    """Resolve the model alias for a request: the key's own override wins, then
    the admin-configured global alias, then the settings default."""
    key_obj = getattr(raw_request.state, "api_key_obj", None)
    return getattr(key_obj, "model_alias", "") or getattr(app.state, "model_alias", settings.model_alias)


def resolve_request_tone(app: FastAPI, model_str: str | None) -> tuple[str, bool]:
    """Resolve an incoming request model name to (tone_value, is_persist).

    Each tone is exposed as its own model via /v1/models, so the requested
    model name now selects the conversation tone. Unmatched names fall back to
    the global default tone (app.state.current_tone)."""
    tone_options = getattr(app.state, "tone_options", None) or _BUILTIN_TONE_OPTIONS
    default_tone = getattr(app.state, "current_tone", "Magic") or "Magic"
    return resolve_tone(model_str, tone_options, default_tone)


def effective_run_permission(app: FastAPI, k: ApiKey | None) -> str:
    """Resolve the run permission for a key, falling back to the global setting."""
    value = ((getattr(k, "run_permission", "") if k is not None else "") or "").strip()
    return value if value in _RUN_PERMISSIONS else getattr(app.state, "run_permission", "full")
