from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from .config import Settings
from .key_store import ApiKey
from .runtime_settings import _RUN_PERMISSIONS
from .substrate_client import _EMPTY_TURN_MARKER, _REFUSED_TURN_MARKER
from .tone_options import TONE_OPTIONS as _BUILTIN_TONE_OPTIONS
from .tone_resolver import resolve_tone


def upstream_http_error(exc: Exception) -> HTTPException:
    """Map a SubstrateCopilotError onto the status code its cause deserves.

    Every failure used to surface as 502, so a turn M365 simply would not answer
    looked identical to a broken gateway: clients retried a refusal that no retry
    can fix, and the operator had nothing to distinguish "this mode is
    unavailable for this account" from "the upstream connection died".

    A refused or twice-empty turn is upstream declining the request itself, so it
    maps to 400 -- the request as phrased will not be served. Everything else
    (idle timeout, closed socket, unusable token) stays 502.

    Keyed on the markers substrate_client raises rather than on exception
    subclasses, matching how mode availability is already classified from these
    same strings.
    """
    detail = str(exc)
    refused = _REFUSED_TURN_MARKER in detail or _EMPTY_TURN_MARKER in detail
    return HTTPException(status_code=400 if refused else 502, detail=detail)


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
