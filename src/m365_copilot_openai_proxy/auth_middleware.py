from __future__ import annotations

import math
import os
import re
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .error_handlers import rate_limit_error_payload
from .ratelimit import RateLimiterRegistry
from .session_helpers import _SESSION_ID_HEADER


def register_auth_middleware(app: FastAPI, resolved_settings: Settings) -> None:
    _allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    _allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()] if _allowed_origins_raw else ["*"]
    _cors_is_wildcard = "*" in _allowed_origins
    # Buckets must outlive the request, so the registry lives on app.state rather
    # than in this closure -- the admin UI reads the effective limits from there.
    if getattr(app.state, "rate_limiters", None) is None:
        app.state.rate_limiters = RateLimiterRegistry()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "x-api-key", "anthropic-version", _SESSION_ID_HEADER],
        max_age=86400,
    )

    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        def with_cors(resp):
            if _cors_is_wildcard:
                resp.headers["Access-Control-Allow-Origin"] = "*"
            else:
                origin = request.headers.get("origin", "")
                if origin in _allowed_origins:
                    resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = f"Content-Type, Authorization, x-api-key, anthropic-version, {_SESSION_ID_HEADER}"
            resp.headers["Access-Control-Max-Age"] = "86400"
            return resp

        path = request.url.path
        if path.startswith("/v1/"):
            app.state.last_request_time = time.time()

        def rate_limited(identity: str, key_obj=None):
            """429 once `identity` has spent its /v1/ budget, else None.

            Checked before the on-demand token refresh below so a throttled
            request never costs a Chromium round-trip.
            """
            if not path.startswith("/v1/"):
                return None
            override = int(getattr(key_obj, "rate_limit_rpm", 0) or 0)
            if override < 0:
                return None  # limiting explicitly waived for this key
            runtime = getattr(app.state, "runtime_settings", None) or {}
            rpm = float(override) if override > 0 else float(runtime.get("rate_limit_rpm") or 0)
            burst = max(1, int(runtime.get("rate_limit_burst") or 15))
            allowed, retry_after = app.state.rate_limiters.try_acquire(identity, rpm, burst)
            if allowed:
                return None
            seconds = max(1, math.ceil(retry_after))
            message = f"Rate limit exceeded ({int(rpm)} requests/minute). Retry after {seconds}s."
            resp = JSONResponse(
                status_code=429,
                content=rate_limit_error_payload(path, message),
            )
            resp.headers["Retry-After"] = str(seconds)
            return resp

        # Deliberately exempt from the rate limit: media is authenticated by the
        # signed URL rather than a key, so there is no identity to meter, and a
        # chat client loading a history full of images would trip any sane ceiling.
        if path == "/v1/m365-media":
            return await call_next(request)

        if path in ("/", "/admin", "/favicon.ico", "/healthz") or path.startswith("/admin/") or path.startswith("/user/"):
            return await call_next(request)

        # Anthropic clients authenticate with a bare "x-api-key" header rather
        # than "Authorization: Bearer" -- the official SDK sends only the former,
        # so keying auth on Bearer alone rejected every /v1/messages caller with
        # a 401 before the route ever ran. Bearer stays first so an explicit
        # Authorization header still wins when a client sends both.
        auth = request.headers.get("Authorization", "")
        match = re.match(r"^Bearer\s+(.+)$", auth, re.IGNORECASE)
        raw_key = match.group(1) if match else request.headers.get("x-api-key", "").strip()

        key_obj = app.state.key_store.resolve(raw_key) if raw_key else None
        if key_obj is not None:
            if not key_obj.enabled:
                return with_cors(JSONResponse(
                    status_code=401,
                    content={"error": {"message": "API key is disabled", "type": "auth_error"}},
                ))
            account = app.state.account_store.get(key_obj.account_id) if key_obj.account_id else None
            limited = rate_limited(key_obj.id, key_obj)
            if limited is not None:
                return with_cors(limited)
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

        if resolved_settings.api_key and raw_key == resolved_settings.api_key:
            limited = rate_limited("__global_key__")
            if limited is not None:
                return with_cors(limited)
            request.state.api_key_obj = None
            request.state.account = None
            return await call_next(request)

        if not resolved_settings.api_key and not app.state.key_store.list():
            limited = rate_limited("__open__")
            if limited is not None:
                return with_cors(limited)
            request.state.api_key_obj = None
            request.state.account = None
            return await call_next(request)

        return with_cors(JSONResponse(
            status_code=401,
            content={"error": {"message": "Invalid API key", "type": "auth_error"}},
        ))
