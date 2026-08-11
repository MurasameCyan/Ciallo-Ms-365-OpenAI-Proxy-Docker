from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request

from .config import Settings
from .key_store import ApiKey
from .runtime_settings import (
    _BUILTIN_CONSUMER_MODE_OPTIONS,
    _RUN_PERMISSIONS,
)
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


def _consumer_mode_options(app: FastAPI) -> list[dict]:
    return (
        getattr(app.state, "consumer_mode_options", None)
        or _BUILTIN_CONSUMER_MODE_OPTIONS
    )


def apply_request_model(
    app: FastAPI,
    raw_request: Request,
    client_factory: Callable[[Request], object],
    model_str: str | None,
) -> tuple[object, str, bool]:
    """Resolve the Provider selector before creating and configuring its client."""
    account = getattr(raw_request.state, "account", None)
    if getattr(account, "provider", "m365") == "consumer":
        mode_options = _consumer_mode_options(app)
        model_key = (model_str or "").strip().lower()
        option = next(
            (
                candidate
                for candidate in mode_options
                if candidate.get("model") == model_key
            ),
            None,
        )
        if option is None:
            available = ", ".join(
                str(candidate.get("model") or "") for candidate in mode_options
            )
            raise ValueError(
                f"Unknown Consumer model '{model_str or ''}'. Available Consumer "
                f"models: {available}"
            )
        client = client_factory(raw_request)
        client.mode = option["mode"]
        client.mode_status = option["status"]
        return client, option["mode"], True

    tone, _is_persist = resolve_request_tone(app, model_str)
    client = client_factory(raw_request)
    client._tone = tone
    return client, tone, False


def build_consumer_models_list(
    mode_options: list[dict], created: int,
) -> list[dict]:
    """Return the configured Consumer model catalogue in live order."""
    return [
        {
            "id": option["model"],
            "object": "model",
            "created": created,
            "owned_by": "microsoft-copilot",
        }
        for option in mode_options
    ]


def effective_run_permission(app: FastAPI, k: ApiKey | None) -> str:
    """Resolve the run permission for a key, falling back to the global setting."""
    value = ((getattr(k, "run_permission", "") if k is not None else "") or "").strip()
    return value if value in _RUN_PERMISSIONS else getattr(app.state, "run_permission", "full")
