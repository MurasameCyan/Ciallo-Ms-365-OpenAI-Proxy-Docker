from __future__ import annotations

import os
import re
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .session_helpers import _SESSION_ID_HEADER


def register_auth_middleware(app: FastAPI, resolved_settings: Settings) -> None:
    _allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    _allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()] if _allowed_origins_raw else ["*"]
    _cors_is_wildcard = "*" in _allowed_origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", _SESSION_ID_HEADER],
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
            resp.headers["Access-Control-Allow-Headers"] = f"Content-Type, Authorization, {_SESSION_ID_HEADER}"
            resp.headers["Access-Control-Max-Age"] = "86400"
            return resp

        path = request.url.path
        if path.startswith("/v1/"):
            app.state.last_request_time = time.time()

        if path == "/v1/m365-image":
            return await call_next(request)

        if path in ("/", "/admin", "/favicon.ico", "/healthz") or path.startswith("/admin/") or path.startswith("/user/"):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        match = re.match(r"^Bearer\s+(.+)$", auth, re.IGNORECASE)
        raw_key = match.group(1) if match else ""

        key_obj = app.state.key_store.resolve(raw_key) if raw_key else None
        if key_obj is not None:
            if not key_obj.enabled:
                return with_cors(JSONResponse(
                    status_code=401,
                    content={"error": {"message": "API key is disabled", "type": "auth_error"}},
                ))
            account = app.state.account_store.get(key_obj.account_id) if key_obj.account_id else None
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
            request.state.api_key_obj = None
            request.state.account = None
            return await call_next(request)

        if not resolved_settings.api_key and not app.state.key_store.list():
            request.state.api_key_obj = None
            request.state.account = None
            return await call_next(request)

        return with_cors(JSONResponse(
            status_code=401,
            content={"error": {"message": "Invalid API key", "type": "auth_error"}},
        ))
