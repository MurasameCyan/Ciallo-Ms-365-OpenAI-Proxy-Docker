from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .build_info import check_for_update, current_build_id, inject_build_info, resolve_build_info
from .templates import _ADMIN_HTML, _LOGIN_HTML, _USER_HTML

# /healthz result reuse window. Short enough that a token expiring is reflected
# promptly, long enough that repeated anonymous polling costs nothing.
_HEALTHZ_CACHE_SECONDS = 5.0


def register_web_routes(
    app: FastAPI,
    admin_secret: str | None,
    admin_session_token: str | None,
    is_admin_authenticated: Callable[[Request], bool],
    login_failures: dict[str, list[float]],
    login_rate_limit: int,
    login_lockout_sec: float,
    require_admin: Callable[[Request], object | None] | None = None,
) -> None:
    @app.get("/healthz")
    async def healthz() -> dict:
        # Cached because this endpoint is unauthenticated: each call stats the
        # token file and JWT-decodes once per account, so an anonymous caller
        # could otherwise drive that work as fast as it can send requests. A few
        # seconds of staleness is irrelevant against token lifetimes measured in
        # hours, and container probes poll far slower than the TTL.
        cached = getattr(app.state, "_healthz_cache", None)
        now = time.monotonic()
        if cached and now - cached[0] < _HEALTHZ_CACHE_SECONDS:
            return cached[1]
        # Report the account pool when one is configured. Requests resolve their
        # token from the account behind the API key, so on a multi-account
        # deployment the global token is unset and reporting only it says nothing
        # about whether the proxy can actually serve traffic.
        accounts = app.state.account_store.list() if getattr(app.state, "account_store", None) else []
        body = {"status": "ok", "token": app.state.token_store.status()}
        if accounts:
            statuses = [acc.token_status() for acc in accounts]
            body["accounts"] = {
                "total": len(statuses),
                "valid": sum(1 for s in statuses if s["valid"]),
            }
        app.state._healthz_cache = (now, body)
        return body

    @app.post("/admin/login")
    async def admin_login(request: Request) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        failures = login_failures.get(client_ip, [])
        failures = [t for t in failures if now - t < login_lockout_sec]
        login_failures[client_ip] = failures
        if len(failures) >= login_rate_limit:
            return JSONResponse({"error": {"message": "Too many login attempts, try again later", "type": "auth_error"}}, status_code=429)

        body = await request.json()
        password = body.get("password", "")
        if admin_secret and secrets.compare_digest(password, admin_secret):
            resp = JSONResponse({"status": "ok"})
            resp.set_cookie("admin_auth", admin_session_token, max_age=86400 * 7, httponly=True, samesite="lax", secure=bool(int(os.environ.get("ADMIN_COOKIE_SECURE", "0"))), path="/")
            return resp
        login_failures.setdefault(client_ip, []).append(now)
        return JSONResponse({"error": {"message": "Wrong password", "type": "auth_error"}}, status_code=401)

    @app.post("/admin/logout")
    async def admin_logout(request: Request) -> Response:
        resp = JSONResponse({"status": "ok"})
        resp.delete_cookie("admin_auth", path="/")
        return resp

    @app.get("/admin/system/version", response_model=None)
    async def admin_system_version(request: Request):
        """Local BUILD_ID only — never hits GitHub (GRA getSystemVersion)."""
        if require_admin is not None:
            err = require_admin(request)
            if err is not None:
                return err
        elif admin_secret and not is_admin_authenticated(request):
            return JSONResponse({"error": {"message": "Admin authentication required", "type": "auth_error"}}, status_code=401)
        info = resolve_build_info()
        build_id = current_build_id()
        return {
            "current": info["hash"] if info["hash"] != "n/a" else build_id,
            "buildId": build_id,
            "version": build_id,
            "repoUrl": info["repo_url"],
            "commitUrl": info["commit_url"],
            "trackRef": info["track_ref"],
        }

    @app.get("/admin/system/update-check", response_model=None)
    async def admin_system_update_check(request: Request):
        """User-triggered compare against GitHub track-ref HEAD (GRA checkUpdate)."""
        if require_admin is not None:
            err = require_admin(request)
            if err is not None:
                return err
        elif admin_secret and not is_admin_authenticated(request):
            return JSONResponse({"error": {"message": "Admin authentication required", "type": "auth_error"}}, status_code=401)
        return await check_for_update()

    @app.get("/", response_class=HTMLResponse)
    async def user_page(request: Request) -> HTMLResponse:
        return HTMLResponse(_USER_HTML, headers={"Cache-Control": "no-store"})

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_page(request: Request) -> HTMLResponse:
        if admin_secret and not is_admin_authenticated(request):
            return HTMLResponse(_LOGIN_HTML, headers={"Cache-Control": "no-store"})
        # Inject short git hash + repo URL for the sidebar (hidden when collapsed).
        return HTMLResponse(inject_build_info(_ADMIN_HTML), headers={"Cache-Control": "no-store"})

    @app.get("/favicon.ico")
    async def favicon() -> Response:
        return Response(status_code=204)
