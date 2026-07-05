from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse, Response

from .config import Settings
from .account_store import Account, AccountStore, extract_identity
from .key_store import ApiKey, KeyStore
from .refresh_scheduler import RefreshScheduler
from .session_store import PersistentSession, PersistentSessionStore
from .substrate_client import SubstrateCopilotClient, SubstrateCopilotError
from .token_store import AccessTokenStore, write_token, write_username, read_username, decode_jwt_payload, is_substrate_token_claims, init_token_dir, write_tone, read_tone, write_tool_prompt, read_tool_prompt, write_system_prompt, read_system_prompt
from .models import AnthropicMessagesRequest, OpenAIChatRequest, OpenAIResponsesRequest
from .translator import translate_anthropic_request, translate_openai_request, translate_responses_request, flatten_content, default_tool_system_prompt
from .templates import _ADMIN_HTML, _LOGIN_HTML, _USER_HTML
from .runtime_settings import (
    _LOG_LEVELS,
    _RUN_PERMISSIONS,
    _RUNTIME_SETTINGS_DEFAULTS,
    _read_runtime_settings,
    _write_runtime_settings,
)
from .tool_call_parser import (
    _RETRY_INSTRUCTION,
    _extract_prose_write,
    _extract_tool_calls,
    _filter_read_only_tool_calls,
    _has_read_only_intent,
    _looks_like_fake_file_claim,
    _strip_tool_call_blocks,
)

_PERSIST_MODEL_SUFFIX = ":persist"
_SESSION_ID_HEADER = "x-m365-session-id"

# Login credential rules (validated server-side; front-end checks are bypassable).
# Username: letters + digits only. Password: letters, digits, and a safe symbol
# subset that excludes quotes/backslash/angle brackets/whitespace so credentials
# can never break out of JSON, HTML attributes, or shell contexts.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9]{1,32}$")
_PASSWORD_RE = re.compile(r"^[A-Za-z0-9!#$%&*+\-.:=?@^_~]{6,64}$")


def _validate_username(username: str) -> str | None:
    """Return an error message if the username is invalid, else None."""
    if not _USERNAME_RE.match(username):
        return "Username must be 1-32 chars, letters and digits only"
    return None


def _validate_password(password: str) -> str | None:
    """Return an error message if the password is invalid, else None."""
    if not _PASSWORD_RE.match(password):
        return "Password must be 6-64 chars: letters, digits, and safe symbols (!#$%&*+-.:=?@^_~)"
    return None


def _detect_conversation_session(request: OpenAIChatRequest) -> tuple[str, str]:
    """Auto-detect conversation session from the request messages.

    Returns (session_id, title):
    - session_id: stable hash based on the first user message content
    - title: first ~60 chars of the first user message for display
    When the user starts a new chat in Trae, the first user message changes -> new session.
    Agentic tool-result turns reuse the same first user message -> same session.
    """
    for msg in request.messages:
        if msg.role == "user":
            text = flatten_content(msg.content).strip()
            if text:
                sid = "conv_" + hashlib.sha256(text.encode()).hexdigest()[:12]
                title = text[:60].replace("\n", " ")
                return sid, title
    # Fallback: random session
    return "conv_" + uuid.uuid4().hex[:12], "New conversation"


def _update_username_from_token(token: str, state) -> None:
    """Extract username from JWT claims and persist it if not already set."""
    if getattr(state, 'username', None) and len(state.username) > 1:
        return  # Already have a valid username, keep it
    try:
        claims = decode_jwt_payload(token)
        name = claims.get("name") or claims.get("upn") or ""
        if isinstance(name, str):
            name = name.strip()
            # If upn is email, take the local part
            if "@" in name and " " not in name:
                name = name.split("@")[0]
        if name and len(name) > 1:
            state.username = name
            write_username(name)
    except Exception:
        pass


def _load_json_list(path: Path, limit: int) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)][-limit:]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _write_json_list(path: Path, data: list[dict], limit: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data[-limit:], ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _load_metrics_history(path: Path) -> list[dict]:
    """Load the persisted metrics time-series (best-effort, empty on any error)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)][-500:]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _maybe_snapshot_metrics(app: FastAPI, min_interval: float = 300.0) -> None:
    """Append a metrics snapshot if enough time has passed since the last one.

    Throttled to `min_interval` seconds and driven by admin polling, so it needs
    no background task. Keeps the last 500 points and persists best-effort.
    """
    now = time.time()
    if now - getattr(app.state, "metrics_last_snapshot", 0.0) < min_interval:
        return
    app.state.metrics_last_snapshot = now
    keys = app.state.key_store.list()
    accts = app.state.account_store.list()
    valid = sum(1 for a in accts if a.token_status().get("valid"))
    snap = {
        "ts": now,
        "users": len(keys),
        "accounts": len(accts),
        "enabled_users": sum(1 for k in keys if k.enabled),
        "valid_accounts": valid,
        "expired_accounts": len(accts) - valid,
    }
    hist = app.state.metrics_history
    hist.append(snap)
    if len(hist) > 500:
        del hist[:-500]
    try:
        app.state.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = app.state.metrics_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
        tmp.replace(app.state.metrics_path)
    except OSError:
        pass


def create_app(
    settings: Settings | None = None,
    copilot_client_factory: Callable[[], SubstrateCopilotClient] | None = None,
) -> FastAPI:
    app = FastAPI(title="Ciallo Ms-365 OpenAI Proxy")
    resolved_settings = settings or Settings()
    init_token_dir(resolved_settings.token_dir)
    app.state.settings = resolved_settings
    app.state.token_store = AccessTokenStore(resolved_settings.access_token)
    app.state.session_store = PersistentSessionStore(
        persist_path=Path(resolved_settings.token_dir) / "sessions.json"
    )  # Persist to mounted volume so conversations survive container restarts
    # Multi-tenant stores: account pool (each owns an isolated token + Chromium
    # profile/CDP port) and API key table (each key bound to one account, scheme B).
    app.state.account_store = AccountStore(
        persist_path=Path(resolved_settings.token_dir) / "accounts.json"
    )
    app.state.key_store = KeyStore(
        persist_path=Path(resolved_settings.token_dir) / "keys.json"
    )
    # On-demand token refresh scheduler: brings one account's Chromium up at a
    # time (serial), captures a fresh token via CDP, then tears it down. Keeps
    # peak memory close to single-tenant even with many accounts.
    app.state.refresh_scheduler = RefreshScheduler(
        app.state.account_store,
        profile_root=Path(resolved_settings.token_dir) / "profiles",
    )
    app.state.call_log_path = Path(resolved_settings.token_dir) / "call_log.json"
    app.state.call_log: list[dict] = _load_json_list(app.state.call_log_path, 100)  # API call log for web UI display
    app.state.captured_payloads: list[dict] = []  # Substrate chat payloads captured via get_token.js for mode comparison
    # Metrics time-series for the home dashboard trend chart. Snapshots are taken
    # lazily (throttled) whenever the admin polls, so no background scheduler is
    # needed. Persisted so the trend survives restarts.
    app.state.metrics_path = Path(resolved_settings.token_dir) / "metrics_history.json"
    app.state.metrics_history: list[dict] = _load_metrics_history(app.state.metrics_path)
    app.state.metrics_last_snapshot = 0.0
    runtime_settings = _read_runtime_settings(resolved_settings.token_dir)
    app.state.runtime_settings = runtime_settings
    app.state.model_alias = runtime_settings["model_alias"]
    app.state.time_zone = runtime_settings["time_zone"]
    app.state.auto_refresh_enabled = runtime_settings["auto_refresh"]
    app.state.refresh_before_seconds = runtime_settings["refresh_before_seconds"]
    app.state.cdp_port = runtime_settings["cdp_port"]
    app.state.account_cdp_port_base = runtime_settings["account_cdp_port_base"]
    app.state.account_store.set_cdp_port_base(app.state.account_cdp_port_base)
    app.state.log_level = runtime_settings["log_level"]
    app.state.run_permission = runtime_settings["run_permission"]
    logging.getLogger().setLevel(app.state.log_level)
    app.state.last_request_time = 0  # 0 means never received any /v1/ request
    app.state.idle_timeout_minutes = runtime_settings["idle_timeout_minutes"]
    app.state.username = read_username()  # Restore persisted username (set via get_token.js push or CDP extraction)
    app.state.current_tone = read_tone() or "Magic"  # Restore persisted conversation tone (mode), default "Magic" (Auto)
    app.state.tool_prompt = read_tool_prompt()  # Restore persisted user-defined extra tool-call instruction
    app.state.system_prompt = read_system_prompt()  # Restore persisted system-level tool-call instruction override (empty = use default)
    if not resolved_settings.api_key:
        print("WARNING: API_KEY is not set. All /v1/ API endpoints are open without authentication. Set API_KEY in .env to secure your instance.")
    _admin_secret = resolved_settings.admin_password or resolved_settings.api_key
    if not _admin_secret:
        print("WARNING: Neither API_KEY nor ADMIN_PASSWORD is set. Web admin page is open without authentication. Set ADMIN_PASSWORD in .env to secure it.")

    # Generate a random admin session token instead of deterministic hash
    _admin_session_token: str | None = secrets.token_hex(32) if _admin_secret else None

    # Login rate limiting: track failed attempts by client IP
    _login_failures: dict[str, list[float]] = {}
    _LOGIN_RATE_LIMIT = 5       # max failures
    _LOGIN_LOCKOUT_SEC = 60.0   # lockout duration

    app.state.copilot_client_factory = copilot_client_factory or (
        lambda token=None, tone=None, tool_prompt=None, time_zone=None: SubstrateCopilotClient(
            token if token is not None else app.state.token_store.get(),
            time_zone if time_zone is not None else getattr(app.state, 'time_zone', 'Asia/Shanghai'),
            tone if tone is not None else getattr(app.state, 'current_tone', 'Magic'),
            tool_prompt if tool_prompt is not None else getattr(app.state, 'tool_prompt', ''),
        )
    )

    def _is_admin_authenticated(request: Request) -> bool:
        """Check if the request has a valid admin auth cookie."""
        if not _admin_secret:
            return True
        if _admin_session_token is None:
            return False
        cookie_val = request.cookies.get("admin_auth", "")
        return secrets.compare_digest(cookie_val, _admin_session_token)

    def _require_admin(request: Request):
        """Check admin cookie auth; return error response or None."""
        if _admin_secret and not _is_admin_authenticated(request):
            return JSONResponse({"error": {"message": "Admin authentication required", "type": "auth_error"}}, status_code=401)
        return None

    # CORS: use configurable origin whitelist (comma-separated ALLOWED_ORIGINS env var)
    _allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    _allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()] if _allowed_origins_raw else ["*"]
    _cors_is_wildcard = "*" in _allowed_origins

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "x-m365-session-id"],
        max_age=86400,
    )

    # API Key authentication middleware (runs after CORS)
    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):
        # Always handle preflight first
        if request.method == "OPTIONS":
            return await call_next(request)
        # Add CORS headers to all responses from this middleware
        def with_cors(resp):
            if _cors_is_wildcard:
                resp.headers["Access-Control-Allow-Origin"] = "*"
            else:
                origin = request.headers.get("origin", "")
                if origin in _allowed_origins:
                    resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, x-m365-session-id"
            resp.headers["Access-Control-Max-Age"] = "86400"
            return resp
        path = request.url.path
        # Track last request time for idle detection & on-demand refresh
        if path.startswith("/v1/"):
            app.state.last_request_time = time.time()

        # Public paths: admin page (own cookie auth), user page, health, and all
        # /admin/* + /user/* endpoints (each does its own cookie/key check).
        if path in ("/", "/admin", "/favicon.ico", "/healthz") or path.startswith("/admin/") or path.startswith("/user/"):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        match = re.match(r"^Bearer\s+(.+)$", auth, re.IGNORECASE)
        raw_key = match.group(1) if match else ""

        # Multi-tenant: resolve the API key -> ApiKey -> bound Account.
        key_obj = app.state.key_store.resolve(raw_key) if raw_key else None
        if key_obj is not None:
            if not key_obj.enabled:
                return with_cors(JSONResponse(
                    status_code=401,
                    content={"error": {"message": "API key is disabled", "type": "auth_error"}},
                ))
            account = app.state.account_store.get(key_obj.account_id) if key_obj.account_id else None
            # Bring the bound account's token up to date on demand (serial, one
            # Chromium at a time). No-op if the token is still valid.
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

        # Legacy single API_KEY fallback (global admin key, no bound account).
        if resolved_settings.api_key and raw_key == resolved_settings.api_key:
            request.state.api_key_obj = None
            request.state.account = None
            return await call_next(request)

        # No auth configured at all (no keys registered and no legacy key): open.
        if not resolved_settings.api_key and not app.state.key_store.list():
            request.state.api_key_obj = None
            request.state.account = None
            return await call_next(request)

        return with_cors(JSONResponse(
            status_code=401,
            content={"error": {"message": "Invalid API key", "type": "auth_error"}},
        ))

    def get_settings() -> Settings:
        return app.state.settings

    def get_copilot_client(raw_request: Request) -> SubstrateCopilotClient:
        try:
            key_obj = getattr(raw_request.state, "api_key_obj", None)
            account = getattr(raw_request.state, "account", None)
            # Per-key overrides: bound account's token + the key's own tone.
            # Tool prompt: the global app.state.tool_prompt acts as a shared base
            # that admins set for everyone, and the key's own tool_prompt is
            # appended on top (global base + user addition).
            token = account.token if account is not None else None
            tone = key_obj.tone if key_obj is not None else None
            global_tp = (getattr(app.state, "tool_prompt", "") or "").strip()
            key_tp = ((key_obj.tool_prompt if key_obj is not None else "") or "").strip()
            tool_prompt = "\n\n".join(p for p in (global_tp, key_tp) if p) or None
            time_zone = getattr(key_obj, "time_zone", "") or getattr(app.state, "time_zone", "Asia/Shanghai")
            return app.state.copilot_client_factory(token=token, tone=tone, tool_prompt=tool_prompt, time_zone=time_zone)
        except TypeError:
            # Test-injected factory may take no arguments.
            return app.state.copilot_client_factory()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Global exception handler — always return JSON (never HTML error pages)
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "internal_error"}},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"message": exc.detail, "type": "http_error"}},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    def _json_err(status: int, message: str, error_type: str = "error") -> JSONResponse:
        """Return a JSON error response with CORS headers."""
        return JSONResponse(
            status_code=status,
            content={"error": {"message": message, "type": error_type}},
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "token": app.state.token_store.status()}

    @app.get("/admin/token/status")
    async def token_status(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        status = app.state.token_store.status()
        status["auto_refresh"] = app.state.auto_refresh_enabled
        status["username"] = (getattr(app.state, 'username', '') or None) if len(getattr(app.state, 'username', '')) > 1 else None
        return status

    @app.post("/admin/token/auto-refresh-toggle")
    async def toggle_auto_refresh(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        app.state.auto_refresh_enabled = not app.state.auto_refresh_enabled
        return {"status": "ok", "auto_refresh": app.state.auto_refresh_enabled}

    @app.post("/admin/token/update")
    async def update_token(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        body = await request.json()
        token = body.get("token", "").strip()
        username = body.get("username", "").strip()
        if not token:
            return _json_err(400, "Token is empty")
        # Extract token from full WebSocket URL if needed
        match = re.search(r"access_token=([^&\s]+)", token)
        if match:
            token = match.group(1)
        if not token.startswith("eyJ"):
            return _json_err(400, "Not a valid JWT token")
        # Write to isolated token file
        write_token(token)
        # Update in-memory store
        app.state.token_store._token = token
        app.state.token_store._mtime_ns = None
        if username and len(username) > 1:
            app.state.username = username
            write_username(username)
        else:
            _update_username_from_token(token, app.state)
        _, email = extract_identity(token)
        if email:
            acc = app.state.account_store.find_by_email(email)
            if acc is not None:
                app.state.account_store.update_token(acc.id, token, token_source="manual")
        return {"status": "ok", "message": "Token updated", "token_status": app.state.token_store.status()}

    @app.post("/admin/token/auto-capture")
    async def auto_capture_token(request: Request) -> dict:
        """Auto-capture token from Chromium CDP running inside the container."""
        err = _require_admin(request)
        if err: return err
        import asyncio
        from .cli import _cdp_extract_token
        cdp_port = int(getattr(app.state, "cdp_port", 9222))
        try:
            token = await _cdp_extract_token(cdp_port, allow_nudge=True)
        except Exception as exc:
            return _json_err(502, f"CDP capture failed: {exc}")
        if not token:
            return _json_err(404, "No substrate token found. Make sure M365 Copilot is open and logged in in Chromium.")
        # Write to token file and update in-memory
        write_token(token)
        app.state.token_store._token = token
        app.state.token_store._mtime_ns = None
        _update_username_from_token(token, app.state)
        return {"status": "ok", "message": "Token auto-captured", "token_status": app.state.token_store.status()}

    @app.post("/admin/cookie/inject")
    async def inject_cookie(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        body = await request.json()
        cookies = body.get("cookies", [])
        username = body.get("username", "")
        if username and len(str(username).strip()) > 1:
            app.state.username = str(username).strip()
            write_username(str(username).strip())
        if not cookies:
            return _json_err(400, "No cookies provided")
        import asyncio as _async
        import httpx as _httpx
        import websockets as _ws

        cdp_port = int(getattr(app.state, "cdp_port", 9222))
        try:
            async with _httpx.AsyncClient(timeout=3) as client:
                tabs = (await client.get(f"http://localhost:{cdp_port}/json")).json()
        except Exception as exc:
            return _json_err(502, f"Cannot connect to Chromium CDP: {exc}")

        tab = next((t for t in tabs if t.get("type") == "page" and t.get("url", "").startswith("https://m365.cloud.microsoft/")), None)
        if not tab:
            tab = next((t for t in tabs if t.get("type") == "page"), None)
        if not tab:
            return _json_err(404, "No browser tab found in Chromium")

        injected = 0
        try:
            async with _ws.connect(tab["webSocketDebuggerUrl"]) as ws:
                await ws.send(json.dumps({"id": 2, "method": "Network.clearBrowserCookies"}))
                try:
                    await _async.wait_for(ws.recv(), timeout=2)
                except (_async.TimeoutError, Exception):
                    pass
                if "m365.cloud.microsoft" not in tab.get("url", ""):
                    await ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": "https://m365.cloud.microsoft/chat"}}))
                    await _async.sleep(3)
                    try:
                        await _async.wait_for(ws.recv(), timeout=2)
                    except (_async.TimeoutError, Exception):
                        pass

                for i, cookie in enumerate(cookies):
                    cookie_params = {
                        "name": cookie.get("name", ""),
                        "value": cookie.get("value", ""),
                        "domain": cookie.get("domain", ".microsoft.com"),
                        "path": cookie.get("path", "/"),
                        "secure": cookie.get("secure", True),
                        "httpOnly": cookie.get("httpOnly", False),
                    }
                    ss = cookie.get("sameSite", "")
                    if ss:
                        ss_cap = ss.capitalize()
                        if ss_cap in ("Strict", "Lax", "None"):
                            cookie_params["sameSite"] = ss_cap
                    # sameSite=None requires secure=true in CDP
                    if cookie_params.get("sameSite") == "None":
                        cookie_params["secure"] = True
                    if cookie.get("expirationDate") or cookie.get("expires"):
                        cookie_params["expires"] = cookie.get("expirationDate") or cookie.get("expires")
                    await ws.send(json.dumps({"id": 100 + i, "method": "Network.setCookie", "params": cookie_params}))
                    try:
                        resp = await _async.wait_for(ws.recv(), timeout=5)
                        result = json.loads(resp)
                        if result.get("result", {}).get("success"):
                            injected += 1
                    except (_async.TimeoutError, Exception):
                        pass

                # Navigate to M365 chat (full load, not just reload)
                await ws.send(json.dumps({"id": 998, "method": "Page.navigate", "params": {"url": "https://m365.cloud.microsoft/chat"}}))
                # Wait for page to load and potentially complete auth redirect
                await _async.sleep(8)
                # Drain any pending CDP messages
                try:
                    while True:
                        await _async.wait_for(ws.recv(), timeout=0.5)
                except (_async.TimeoutError, Exception):
                    pass
        except Exception as exc:
            return _json_err(502, f"CDP cookie injection failed: {exc}")

        return {"status": "ok", "message": f"Injected {injected}/{len(cookies)} cookies. Page navigating to M365...", "injected": injected, "total": len(cookies)}

    @app.get("/admin/chromium/login-status")
    async def chromium_login_status(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        import httpx as _httpx
        import websockets as _ws
        import asyncio as _async

        cdp_port = int(getattr(app.state, "cdp_port", 9222))
        # Check CDP availability
        try:
            async with _httpx.AsyncClient(timeout=3) as client:
                tabs = (await client.get(f"http://localhost:{cdp_port}/json")).json()
        except Exception:
            return {"chromium_running": False, "logged_in": False, "url": None, "title": None, "cookies": []}

        # Find M365 tab
        tab = next((t for t in tabs if t.get("type") == "page" and "m365.cloud.microsoft" in t.get("url", "")), None)
        if not tab:
            tab = next((t for t in tabs if t.get("type") == "page"), None)

        if not tab:
            return {"chromium_running": True, "logged_in": False, "url": None, "title": None, "cookies": []}

        # Try to detect login state via CDP
        logged_in = False
        page_title = tab.get("title", "")
        page_url = tab.get("url", "")
        cookie_details = []
        # Extract username: prefer CDP extraction, fallback to app.state.username (set by get_token.js push)
        username = getattr(app.state, 'username', '') or None
        try:
            async with _ws.connect(tab["webSocketDebuggerUrl"]) as ws:
                # Get page cookies for M365 domain
                await ws.send(json.dumps({"id": 1, "method": "Network.getCookies", "params": {"urls": ["https://m365.cloud.microsoft", "https://login.microsoftonline.com", "https://microsoft.com", "https://office.com"]}}))
                resp = await _async.wait_for(ws.recv(), timeout=5)
                result = json.loads(resp)
                cookies = result.get("result", {}).get("cookies", [])
                cookie_details = [{"name": c.get("name", ""), "domain": c.get("domain", ""), "httpOnly": c.get("httpOnly", False), "secure": c.get("secure", False)} for c in cookies]
                # Check for authentication cookies
                auth_cookie_names = {"SignInStateCookie", "ESTSAUTH", "ESTSAUTHPERSISTENT", "brcap", "MUID"}
                found = any(c.get("name", "") in auth_cookie_names for c in cookies)
                # Also check URL — if redirected to login page, not logged in
                if "login.microsoftonline.com" in page_url or "login.windows.net" in page_url:
                    logged_in = False
                elif found or "m365.cloud.microsoft/chat" in page_url:
                    logged_in = True
                else:
                    logged_in = False
                # Extract username from page JS (try multiple sources)
                if logged_in:
                    try:
                        _USER_JS = """(() => {
                            try { const s = sessionStorage.getItem('ms-m365-shell-session-data'); if (s) { const d = JSON.parse(s); if (d && d.userDisplayName) return d.userDisplayName; if (d && d.upn) return d.upn.split('@')[0]; } } catch {}
                            try {
                                const av = document.querySelectorAll('[data-testid="header-person-menu"], [data-testid="persona"], button[aria-label*="Account"], button[aria-label*="Manager"], [role="button"][aria-label*="for "], [role="button"][title*="for "], [role="button"][aria-label*="概要"]');
                                for (const el of av) {
                                    const a = el.getAttribute('aria-label') || el.getAttribute('title') || '';
                                    const m = a.match(/(?:for\\s+|的[帐账]户(?:管理器)?[：:]?\\s*)(.+)/i) || a.match(/^(.+?)(?:\\s*\\(|\\s*-|\\s*的)/);
                                    if (m && m[1] && m[1].trim().length > 1 && m[1].trim().length < 80) return m[1].trim();
                                    if (a && a.length > 1 && a.length < 80 && !/^(home|copilot|apps|chat|create|menu|back|close)$/i.test(a)) return a.trim();
                                }
                            } catch {}
                            try {
                                const els = document.querySelectorAll('[data-testid="header-person-menu"], [data-testid="persona"], [aria-label*="Account"], [aria-label*="Profiles"], .ms-Icon--People, button[title*="Account"], span[id*="person"]');
                                for (const el of els) { const t = el.textContent.trim(); if (t && t.length > 1 && t.length < 80) return t; }
                            } catch {}
                            try {
                                const profile = document.querySelector('div[class*="persona"] span, div[class*="UserProfile"] span, img[alt]'); if (profile) { const a = profile.getAttribute('alt') || profile.textContent; if (a && a.trim() && a.trim().length > 1) return a.trim(); } } catch {}
                            try {
                                const fus = document.querySelectorAll('span.fui-Text, span[class*="fai-bebop"]');
                                const skip = /^(home|copilot|apps|chat|create|new|file|edit|view|insert|format|tools|help|share|send|save|open|close|settings|back|next|previous|more|menu|search|filter|sort|refresh|delete|cancel|ok|yes|no)$/i;
                                for (const el of fus) { const t = el.textContent.trim(); if (t && t.length > 1 && t.length < 80 && !skip.test(t)) return t; }
                            } catch {}
                            return null;
                        })()"""
                        next_id = 2
                        # Drain any pending CDP messages before sending
                        while True:
                            try:
                                await _async.wait_for(ws.recv(), timeout=0.1)
                            except (_async.TimeoutError, Exception):
                                break
                        await ws.send(json.dumps({"id": next_id, "method": "Runtime.evaluate", "params": {"expression": _USER_JS}}))
                        # Wait for the specific response by id
                        deadline = _async.get_event_loop().time() + 3
                        while _async.get_event_loop().time() < deadline:
                            raw_msg = await _async.wait_for(ws.recv(), timeout=2)
                            msg = json.loads(raw_msg)
                            if msg.get("id") == next_id:
                                name_val = msg.get("result", {}).get("result", {}).get("value")
                                if name_val and isinstance(name_val, str) and len(name_val.strip()) > 1:
                                    username = name_val.strip()
                                    app.state.username = username
                                    write_username(username)
                                break
                    except Exception:
                        pass
        except Exception:
            logged_in = "m365.cloud.microsoft/chat" in page_url

        # Fallback to persisted username if CDP extraction returned nothing
        if not username:
            username = getattr(app.state, 'username', '') or None

        return {
            "chromium_running": True,
            "logged_in": logged_in,
            "username": username,
            "url": page_url,
            "title": page_title,
            "cookies": cookie_details,
        }

    @app.post("/admin/chromium/logout")
    async def chromium_logout(request: Request) -> dict:
        """Logout from M365 in Chromium by clearing cookies and navigating to login page."""
        err = _require_admin(request)
        if err: return err
        import httpx as _httpx
        import websockets as _ws
        import asyncio as _async

        cdp_port = int(getattr(app.state, "cdp_port", 9222))
        try:
            async with _httpx.AsyncClient(timeout=3) as client:
                tabs = (await client.get(f"http://localhost:{cdp_port}/json")).json()
        except Exception as exc:
            return _json_err(502, f"Cannot connect to Chromium CDP: {exc}")

        tab = next((t for t in tabs if t.get("type") == "page" and "m365.cloud.microsoft" in t.get("url", "")), None)
        if not tab:
            tab = next((t for t in tabs if t.get("type") == "page"), None)
        if not tab:
            return _json_err(404, "No browser tab found in Chromium")

        try:
            async with _ws.connect(tab["webSocketDebuggerUrl"]) as ws:
                # Clear all cookies for Microsoft domains
                await ws.send(json.dumps({"id": 1, "method": "Network.getCookies", "params": {"urls": ["https://m365.cloud.microsoft", "https://login.microsoftonline.com", "https://microsoft.com", "https://office.com"]}}))
                resp = await _async.wait_for(ws.recv(), timeout=5)
                result = json.loads(resp)
                cookies = result.get("result", {}).get("cookies", [])
                cleared = 0
                for i, c in enumerate(cookies):
                    await ws.send(json.dumps({"id": 100 + i, "method": "Network.deleteCookies", "params": {"name": c.get("name", ""), "domain": c.get("domain", "")}}))
                    try:
                        await _async.wait_for(ws.recv(), timeout=2)
                        cleared += 1
                    except Exception:
                        pass
                # Clear sessionStorage and localStorage
                await ws.send(json.dumps({"id": 500, "method": "Runtime.evaluate", "params": {"expression": "sessionStorage.clear();localStorage.clear();true"}}))
                try:
                    await _async.wait_for(ws.recv(), timeout=3)
                except Exception:
                    pass
                # Navigate to login page
                await ws.send(json.dumps({"id": 501, "method": "Page.navigate", "params": {"url": "https://m365.cloud.microsoft/chat"}}))
                try:
                    await _async.wait_for(ws.recv(), timeout=5)
                except Exception:
                    pass
        except Exception as exc:
            return _json_err(502, f"CDP logout failed: {exc}")

        app.state.username = ""
        write_username("")
        return {"status": "ok", "message": f"Logged out. Cleared {cleared}/{len(cookies)} cookies.", "username": ""}

    @app.post("/admin/login")
    async def admin_login(request: Request) -> Response:
        # Rate limiting: check if client IP is locked out
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        failures = _login_failures.get(client_ip, [])
        # Remove expired entries
        failures = [t for t in failures if now - t < _LOGIN_LOCKOUT_SEC]
        _login_failures[client_ip] = failures
        if len(failures) >= _LOGIN_RATE_LIMIT:
            return JSONResponse({"error": {"message": "Too many login attempts, try again later", "type": "auth_error"}}, status_code=429)

        body = await request.json()
        password = body.get("password", "")
        if _admin_secret and secrets.compare_digest(password, _admin_secret):
            resp = JSONResponse({"status": "ok"})
            resp.set_cookie("admin_auth", _admin_session_token, max_age=86400 * 7, httponly=True, samesite="lax", secure=bool(int(os.environ.get("ADMIN_COOKIE_SECURE", "0"))), path="/")
            return resp
        # Record failed attempt
        _login_failures.setdefault(client_ip, []).append(now)
        return JSONResponse({"error": {"message": "Wrong password", "type": "auth_error"}}, status_code=401)

    @app.post("/admin/logout")
    async def admin_logout(request: Request) -> Response:
        """Clear the admin_auth cookie so the console requires re-login."""
        resp = JSONResponse({"status": "ok"})
        resp.delete_cookie("admin_auth", path="/")
        return resp

    @app.get("/admin/call-log")
    async def get_call_log(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        return {"logs": getattr(app.state, 'call_log', [])}

    @app.post("/admin/call-log/clear")
    async def clear_call_log(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        app.state.call_log = []
        _write_json_list(app.state.call_log_path, app.state.call_log, 100)
        return {"status": "ok"}

    @app.get("/admin/metrics-history")
    async def get_metrics_history(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        _maybe_snapshot_metrics(app)  # lazy, throttled snapshot on poll
        return {"history": getattr(app.state, 'metrics_history', [])}

    @app.post("/admin/metrics-history/clear")
    async def clear_metrics_history(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        app.state.metrics_history = []
        app.state.metrics_last_snapshot = time.time()
        _write_json_list(app.state.metrics_path, app.state.metrics_history, 500)
        return {"status": "ok"}

    @app.get("/admin/summary")
    async def get_summary(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        accounts = app.state.account_store.list()
        keys = app.state.key_store.list()
        valid_accounts = sum(1 for a in accounts if a.token_status().get("valid"))
        enabled_keys = sum(1 for k in keys if k.enabled)
        bound_keys = sum(1 for k in keys if k.account_id)
        return {
            "accounts_total": len(accounts),
            "accounts_valid": valid_accounts,
            "accounts_expired": len(accounts) - valid_accounts,
            "keys_total": len(keys),
            "keys_enabled": enabled_keys,
            "keys_disabled": len(keys) - enabled_keys,
            "keys_bound": bound_keys,
            "keys_unbound": len(keys) - bound_keys,
        }

    @app.get("/admin/stats")
    async def get_stats(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        now = time.time()
        logs = getattr(app.state, 'call_log', [])
        calls_24h = sum(1 for l in logs if (now - l.get("ts", 0)) <= 86400)
        tone_counts: dict[str, int] = {}
        for l in logs:
            tn = l.get("tone") or "Magic"
            tone_counts[tn] = tone_counts.get(tn, 0) + 1
        # Accounts expiring within 10 minutes, for the account-page warning carousel.
        expiring_accounts = []
        for a in app.state.account_store.list():
            st = a.token_status()
            rem = st.get("seconds_remaining")
            if st.get("valid") and rem is not None and 0 <= rem <= 600:
                expiring_accounts.append({"name": a.name or a.id, "email": a.email, "seconds_remaining": rem})
        expiring_accounts.sort(key=lambda x: x["seconds_remaining"])
        return {
            "calls_total": len(logs),
            "calls_24h": calls_24h,
            "tone_counts": tone_counts,
            "expiring_accounts": expiring_accounts,
        }

    # Max accepted capture-payload body size (bytes). Cheap DoS guard: reject
    # oversized pushes before reading them into memory.
    _CAPTURE_MAX_BYTES = 256 * 1024

    @app.post("/admin/capture-payload")
    async def capture_payload(request: Request) -> dict:
        # Gate first, parse last — reject cheaply before touching the body.
        # The Tampermonkey script pushes cross-origin and cannot carry the
        # admin cookie, so the debug-page toggle is the gate here (not admin
        # auth): when off, every push is rejected outright.
        if not getattr(app.state, "capture_enabled", False):
            return _json_err(403, "capture receiving is disabled")
        # body size limit (avoid parsing huge junk payloads)
        try:
            clen = int(request.headers.get("content-length") or 0)
        except ValueError:
            clen = 0
        if clen > _CAPTURE_MAX_BYTES:
            return _json_err(413, "payload too large")
        raw = await request.body()
        if len(raw) > _CAPTURE_MAX_BYTES:
            return _json_err(413, "payload too large")
        try:
            body = json.loads(raw or b"{}")
        except (ValueError, TypeError):
            return _json_err(400, "invalid json")
        payloads = body.get("payloads", [])
        if not isinstance(payloads, list):
            return _json_err(400, "payloads must be a list")
        app.state.captured_payloads = payloads[:20]
        return {"status": "ok", "count": len(app.state.captured_payloads)}

    @app.get("/admin/capture-payload")
    async def get_captured_payload(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        return {"payloads": getattr(app.state, 'captured_payloads', [])}

    @app.post("/admin/capture-payload/clear")
    async def clear_captured_payload(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        app.state.captured_payloads = []
        return {"status": "ok"}

    @app.get("/admin/capture-toggle")
    async def get_capture_toggle(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        return {"enabled": bool(getattr(app.state, "capture_enabled", False))}

    @app.post("/admin/capture-toggle")
    async def set_capture_toggle(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        app.state.capture_enabled = bool(body.get("enabled"))
        return {"enabled": app.state.capture_enabled}

    # Conversation tone (mode) options discovered from M365 Copilot's mode picker.
    # The `tone` field in the Substrate chat payload controls which model/mode is used.
    _TONE_OPTIONS = [
        {"value": "Magic", "label": "自动 / Auto", "label_zh": "自动", "label_en": "Auto"},
        {"value": "Chat", "label": "快速答复 / Fast", "label_zh": "快速答复", "label_en": "Fast"},
        {"value": "Reasoning", "label": "深度思考 / Think", "label_zh": "深度思考", "label_en": "Think"},
        {"value": "Gpt_5_5_Chat", "label": "GPT 5.5 快速响应", "label_zh": "GPT 5.5 快速响应", "label_en": "GPT 5.5 Fast"},
        {"value": "Gpt_5_5_Reasoning", "label": "GPT 5.5 深度思考", "label_zh": "GPT 5.5 深度思考", "label_en": "GPT 5.5 Think"},
        {"value": "Gpt_5_2_Chat", "label": "GPT 5.2 快速响应", "label_zh": "GPT 5.2 快速响应", "label_en": "GPT 5.2 Fast"},
        {"value": "Gpt_5_2_Reasoning", "label": "GPT 5.2 深度思考", "label_zh": "GPT 5.2 深度思考", "label_en": "GPT 5.2 Think"},
    ]
    _TONE_VALUES = {o["value"] for o in _TONE_OPTIONS}

    @app.get("/admin/tone")
    async def get_tone(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        return {"tone": getattr(app.state, 'current_tone', 'Magic'), "options": _TONE_OPTIONS}

    @app.post("/admin/tone")
    async def set_tone(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        body = await request.json()
        tone = (body.get("tone") or "").strip()
        if tone not in _TONE_VALUES:
            return _json_err(400, f"Invalid tone. Allowed: {', '.join(sorted(_TONE_VALUES))}")
        app.state.current_tone = tone
        write_tone(tone)
        return {"status": "ok", "tone": tone}

    @app.get("/admin/runtime-settings")
    async def get_runtime_settings(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        return {"settings": dict(getattr(app.state, "runtime_settings", _RUNTIME_SETTINGS_DEFAULTS))}

    @app.post("/admin/runtime-settings")
    async def set_runtime_settings(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        body = await request.json()
        current = dict(getattr(app.state, "runtime_settings", _RUNTIME_SETTINGS_DEFAULTS))
        def int_setting(name: str, minimum: int) -> int:
            try:
                return max(minimum, int(body.get(name, current[name])))
            except (TypeError, ValueError):
                return int(current[name])
        data = {
            "time_zone": str(body.get("time_zone", current["time_zone"])).strip() or _RUNTIME_SETTINGS_DEFAULTS["time_zone"],
            "model_alias": str(body.get("model_alias", current["model_alias"])).strip() or _RUNTIME_SETTINGS_DEFAULTS["model_alias"],
            "auto_refresh": bool(body.get("auto_refresh", current["auto_refresh"])),
            "refresh_before_seconds": int_setting("refresh_before_seconds", 0),
            "idle_timeout_minutes": int_setting("idle_timeout_minutes", 1),
            "cdp_port": int_setting("cdp_port", 1),
            "account_cdp_port_base": int_setting("account_cdp_port_base", 1),
            "log_level": str(body.get("log_level", current["log_level"])).strip().upper() or _RUNTIME_SETTINGS_DEFAULTS["log_level"],
            "run_permission": str(body.get("run_permission", current["run_permission"])).strip() or _RUNTIME_SETTINGS_DEFAULTS["run_permission"],
        }
        if data["log_level"] not in _LOG_LEVELS:
            return _json_err(400, "Invalid log level")
        if data["run_permission"] not in _RUN_PERMISSIONS:
            return _json_err(400, "Invalid run permission")
        app.state.runtime_settings = data
        app.state.time_zone = data["time_zone"]
        app.state.model_alias = data["model_alias"]
        app.state.auto_refresh_enabled = data["auto_refresh"]
        app.state.refresh_before_seconds = data["refresh_before_seconds"]
        app.state.idle_timeout_minutes = data["idle_timeout_minutes"]
        app.state.cdp_port = data["cdp_port"]
        app.state.account_cdp_port_base = data["account_cdp_port_base"]
        app.state.account_store.set_cdp_port_base(app.state.account_cdp_port_base)
        app.state.log_level = data["log_level"]
        logging.getLogger().setLevel(app.state.log_level)
        _write_runtime_settings(resolved_settings.token_dir, data)
        return {"status": "ok", "settings": data}

    @app.get("/admin/tool-prompt")
    async def get_tool_prompt(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        return {"tool_prompt": getattr(app.state, 'tool_prompt', '')}

    @app.post("/admin/tool-prompt")
    async def set_tool_prompt(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        body = await request.json()
        prompt = body.get("tool_prompt")
        if not isinstance(prompt, str):
            return _json_err(400, "tool_prompt must be a string")
        prompt = prompt[:4000]  # cap length to avoid bloating every request
        app.state.tool_prompt = prompt
        write_tool_prompt(prompt)
        return {"status": "ok", "tool_prompt": prompt}

    @app.get("/admin/system-prompt")
    async def get_system_prompt(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        # Return the saved override plus the built-in default (for restore/initial fill).
        return {
            "system_prompt": getattr(app.state, 'system_prompt', ''),
            "default": default_tool_system_prompt(),
        }

    @app.post("/admin/system-prompt")
    async def set_system_prompt(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        body = await request.json()
        prompt = body.get("system_prompt")
        if not isinstance(prompt, str):
            return _json_err(400, "system_prompt must be a string")
        prompt = prompt[:8000]  # cap length to avoid bloating every request
        app.state.system_prompt = prompt
        write_system_prompt(prompt)
        return {"status": "ok", "system_prompt": prompt}

    # ============================ Multi-tenant admin API ============================
    def _account_public(acc: Account, bound_keys: list[ApiKey] | None = None) -> dict:
        """Serialize an account for the admin UI (never leak the raw token)."""
        keys = bound_keys if bound_keys is not None else app.state.key_store.list_for_account(acc.id)
        return {
            "id": acc.id,
            "name": acc.name,
            "email": acc.email,
            "cdp_port": acc.cdp_port,
            "token_source": acc.token_source,
            "cookie_valid": bool(getattr(acc, "cookie_valid", False)),
            "cookie_updated_at": getattr(acc, "cookie_updated_at", 0.0),
            "cookie_expires_at": getattr(acc, "cookie_expires_at", 0.0),
            "has_token": bool(acc.token),
            "token_status": acc.token_status(),
            "key_count": len(keys),
            "bound_names": [k.name or k.username or k.id for k in keys],
            "created_at": acc.created_at,
            "updated_at": acc.updated_at,
        }

    def _effective_run_permission(k: ApiKey | None) -> str:
        value = ((getattr(k, "run_permission", "") if k is not None else "") or "").strip()
        return value if value in _RUN_PERMISSIONS else getattr(app.state, "run_permission", "full")

    def _key_public(k: ApiKey) -> dict:
        """Serialize an API key for the admin UI (raw key shown so admin can copy)."""
        acc = app.state.account_store.get(k.account_id) if k.account_id else None
        return {
            "id": k.id,
            "key": k.key,
            "name": k.name,
            "account_id": k.account_id,
            "account_name": acc.name if acc is not None else "",
            "account_source": acc.token_source if acc is not None else "",
            "enabled": k.enabled,
            "tone": k.tone,
            "tool_prompt": k.tool_prompt,
            "system_prompt": k.system_prompt,
            "run_permission": getattr(k, "run_permission", ""),
            "effective_run_permission": _effective_run_permission(k),
            "username": k.username,
            "password": k.password,
            "has_password": bool(k.password_hash),
            "role": k.role,
            "created_at": k.created_at,
            "updated_at": k.updated_at,
        }

    @app.get("/admin/accounts")
    async def list_accounts(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        keys_by_account: dict[str, list[ApiKey]] = {}
        for k in app.state.key_store.list():
            if k.account_id:
                keys_by_account.setdefault(k.account_id, []).append(k)
        return {"accounts": [_account_public(a, keys_by_account.get(a.id, [])) for a in app.state.account_store.list()]}

    @app.post("/admin/accounts")
    async def add_account(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        body = await request.json()
        name = str(body.get("name", "")).strip()
        token = str(body.get("token", "")).strip()
        if token:
            match = re.search(r"access_token=([^&\s]+)", token)
            token = match.group(1) if match else token
            try:
                claims = decode_jwt_payload(token)
                if not is_substrate_token_claims(claims):
                    return _json_err(400, "Token is not a substrate.office.com token")
            except Exception:
                return _json_err(400, "Not a valid JWT token")
        acc = app.state.account_store.add(name=name, token=token,
                                          token_source="manual" if token else "cdp")
        return {"status": "ok", "account": _account_public(acc)}

    @app.post("/admin/accounts/{acc_id}/token")
    async def update_account_token(acc_id: str, request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        body = await request.json()
        token = str(body.get("token", "")).strip()
        if not token:
            return _json_err(400, "Token is empty")
        match = re.search(r"access_token=([^&\s]+)", token)
        token = match.group(1) if match else token
        try:
            claims = decode_jwt_payload(token)
            if not is_substrate_token_claims(claims):
                return _json_err(400, "Token is not a substrate.office.com token")
        except Exception:
            return _json_err(400, "Not a valid JWT token")
        acc = app.state.account_store.update_token(acc_id, token, token_source="manual")
        if acc is None:
            return _json_err(404, "Account not found")
        return {"status": "ok", "account": _account_public(acc)}

    @app.post("/admin/accounts/{acc_id}/token/clear")
    async def clear_account_token(acc_id: str, request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        acc = app.state.account_store.clear_token(acc_id)
        if acc is None:
            return _json_err(404, "Account not found")
        return {"status": "ok", "account": _account_public(acc)}

    @app.post("/admin/accounts/{acc_id}/rename")
    async def rename_account(acc_id: str, request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        body = await request.json()
        name = str(body.get("name", "")).strip()
        acc = app.state.account_store.rename(acc_id, name)
        if acc is None:
            return _json_err(404, "Account not found")
        return {"status": "ok", "account": _account_public(acc)}

    @app.post("/admin/accounts/{acc_id}/refresh")
    async def refresh_account(acc_id: str, request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        if app.state.account_store.get(acc_id) is None:
            return _json_err(404, "Account not found")
        try:
            ok = await app.state.refresh_scheduler.ensure_fresh(acc_id, force=True)
        except Exception as exc:
            return _json_err(502, f"Refresh failed: {exc}")
        acc = app.state.account_store.get(acc_id)
        return {"status": "ok", "refreshed": ok, "account": _account_public(acc) if acc else None}

    @app.post("/admin/accounts/{acc_id}/cookie-refresh")
    async def refresh_account_cookie(acc_id: str, request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        if app.state.account_store.get(acc_id) is None:
            return _json_err(404, "Account not found")
        try:
            ok = await app.state.refresh_scheduler.ensure_fresh(acc_id, force=True)
        except Exception as exc:
            return _json_err(502, f"Cookie refresh failed: {exc}")
        acc = app.state.account_store.get(acc_id)
        return {"status": "ok", "refreshed": ok, "account": _account_public(acc) if acc else None}

    @app.delete("/admin/accounts/{acc_id}")
    async def remove_account(acc_id: str, request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        if not app.state.account_store.remove(acc_id):
            return _json_err(404, "Account not found")
        app.state.key_store.detach_account(acc_id)  # unbind keys that pointed here
        return {"status": "ok"}

    @app.get("/admin/keys")
    async def list_keys(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        return {"keys": [_key_public(k) for k in app.state.key_store.list()]}

    @app.post("/admin/keys")
    async def add_key(request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        body = await request.json()
        name = str(body.get("name", "")).strip()
        account_id = str(body.get("account_id", "")).strip()
        # New keys inherit the global default tone (admin's "对话模式（默认）")
        # unless an explicit tone is provided; the user can override it later.
        tone = str(body.get("tone", "")).strip() or getattr(app.state, 'current_tone', 'Magic')
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        if tone not in _TONE_VALUES:
            return _json_err(400, f"Invalid tone. Allowed: {', '.join(sorted(_TONE_VALUES))}")
        if account_id and app.state.account_store.get(account_id) is None:
            return _json_err(404, "Bound account not found")
        if username:
            uerr = _validate_username(username)
            if uerr:
                return _json_err(400, uerr)
            if app.state.key_store.resolve_by_login_username(username) is not None:
                return _json_err(409, "Username already exists")
            if password:
                perr = _validate_password(password)
                if perr:
                    return _json_err(400, perr)
            else:
                # Password left blank: auto-generate one so the user can actually
                # log in. It's stored/shown in plaintext, so the admin can read it
                # from the key table and hand it over.
                password = secrets.token_urlsafe(9)
        elif password:
            return _json_err(400, "Password requires a username")
        role = str(body.get("role", "user")).strip() or "user"
        if role not in ("user", "admin"):
            return _json_err(400, "Invalid role. Allowed: user, admin")
        k = app.state.key_store.add(name=name, account_id=account_id, tone=tone,
                                    username=username, password=password, role=role)
        return {"status": "ok", "key": _key_public(k)}

    @app.post("/admin/keys/{key_id}")
    async def update_key(key_id: str, request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        body = await request.json()
        fields: dict = {}
        if "name" in body:
            fields["name"] = str(body["name"]).strip()
        if "account_id" in body:
            aid = str(body["account_id"]).strip()
            if aid and app.state.account_store.get(aid) is None:
                return _json_err(404, "Bound account not found")
            fields["account_id"] = aid
        if "enabled" in body:
            fields["enabled"] = bool(body["enabled"])
        if "tone" in body:
            tone = str(body["tone"]).strip() or "Magic"
            if tone not in _TONE_VALUES:
                return _json_err(400, f"Invalid tone. Allowed: {', '.join(sorted(_TONE_VALUES))}")
            fields["tone"] = tone
        if "tool_prompt" in body:
            if not isinstance(body["tool_prompt"], str):
                return _json_err(400, "tool_prompt must be a string")
            fields["tool_prompt"] = body["tool_prompt"][:4000]
        if "system_prompt" in body:
            if not isinstance(body["system_prompt"], str):
                return _json_err(400, "system_prompt must be a string")
            fields["system_prompt"] = body["system_prompt"][:8000]
        if "run_permission" in body:
            rp = str(body["run_permission"]).strip()
            if rp and rp not in _RUN_PERMISSIONS:
                return _json_err(400, "Invalid run permission")
            fields["run_permission"] = rp
        if "username" in body:
            uname = str(body["username"]).strip()
            if uname:
                uerr = _validate_username(uname)
                if uerr:
                    return _json_err(400, uerr)
                existing = app.state.key_store.resolve_by_login_username(uname)
                if existing is not None and existing.id != key_id:
                    return _json_err(409, "Username already exists")
            fields["username"] = uname
        if "password" in body:
            if not isinstance(body["password"], str):
                return _json_err(400, "password must be a string")
            if body["password"]:
                perr = _validate_password(body["password"])
                if perr:
                    return _json_err(400, perr)
                fields["password"] = body["password"]
        if "role" in body:
            role = str(body["role"]).strip() or "user"
            if role not in ("user", "admin"):
                return _json_err(400, "Invalid role. Allowed: user, admin")
            fields["role"] = role
        k = app.state.key_store.update(key_id, **fields)
        if k is None:
            return _json_err(404, "Key not found")
        return {"status": "ok", "key": _key_public(k)}

    @app.post("/admin/keys/{key_id}/regenerate")
    async def regenerate_key(key_id: str, request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        k = app.state.key_store.regenerate_key(key_id)
        if k is None:
            return _json_err(404, "Key not found")
        return {"status": "ok", "key": _key_public(k)}

    @app.delete("/admin/keys/{key_id}")
    async def remove_key(key_id: str, request: Request) -> dict:
        err = _require_admin(request)
        if err: return err
        if not app.state.key_store.remove(key_id):
            return _json_err(404, "Key not found")
        return {"status": "ok"}

    # ============================ User self-service API ============================
    def _resolve_user_key(request: Request) -> ApiKey | None:
        """Resolve the caller's own ApiKey from the Authorization header.

        /user/* paths bypass the auth middleware, so they authenticate here by
        their own API key instead of an admin cookie.
        """
        auth = request.headers.get("Authorization", "")
        m = re.match(r"^Bearer\s+(.+)$", auth, re.IGNORECASE)
        if not m:
            return None
        return app.state.key_store.resolve(m.group(1).strip())

    @app.post("/user/login")
    async def user_login(request: Request) -> dict:
        """Exchange a username + password for the caller's raw API key.

        The user page logs in with credentials (not the raw key). On success we
        hand back the key so the browser keeps using Bearer auth for /user/* and
        /v1/* — no change needed downstream.
        """
        body = await request.json()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        if not username or not password:
            return _json_err(400, "Username and password are required", "auth_error")
        k = app.state.key_store.resolve_by_login(username, password)
        if k is None:
            return _json_err(401, "Wrong username or password", "auth_error")
        if not k.enabled:
            return _json_err(403, "This account is disabled", "auth_error")
        return {"status": "ok", "key": k.key, "name": k.name or k.username}

    @app.post("/user/repassword")
    async def user_repassword(request: Request) -> dict:
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        body = await request.json()
        old_password = str(body.get("old_password", ""))
        new_password = str(body.get("new_password", ""))
        if not old_password or not new_password:
            return _json_err(400, "Old password and new password are required", "auth_error")
        if not k.check_password(old_password):
            return _json_err(401, "Wrong password", "auth_error")
        perr = _validate_password(new_password)
        if perr:
            return _json_err(400, perr)
        app.state.key_store.update(k.id, password=new_password)
        return {"status": "ok"}

    @app.get("/user/me")
    async def user_me(request: Request) -> dict:
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        acc = app.state.account_store.get(k.account_id) if k.account_id else None
        return {
            "name": k.name,
            "enabled": k.enabled,
            "tone": k.tone,
            "tool_prompt": k.tool_prompt,
            "system_prompt": k.system_prompt,
            "model_alias": getattr(k, "model_alias", "") or getattr(app.state, "model_alias", resolved_settings.model_alias),
            "time_zone": getattr(k, "time_zone", "") or getattr(app.state, "time_zone", "Asia/Shanghai"),
            "run_permission": getattr(k, "run_permission", ""),
            "effective_run_permission": _effective_run_permission(k),
            "default_run_permission": getattr(app.state, "run_permission", "full"),
            "default_system_prompt": default_tool_system_prompt(),
            "displaced": bool(getattr(k, "displaced_at", 0.0)),
            "displaced_at": getattr(k, "displaced_at", 0.0),
            "account": {
                "id": acc.id,
                "name": acc.name,
                "email": acc.email,
                "token_source": acc.token_source,
                "updated_at": acc.updated_at,
                "has_token": bool(acc.token),
                "cookie_valid": bool(getattr(acc, "cookie_valid", False)),
                "cookie_updated_at": getattr(acc, "cookie_updated_at", 0.0),
                "cookie_expires_at": getattr(acc, "cookie_expires_at", 0.0),
                "token_status": acc.token_status(),
            } if acc is not None else None,
            "tone_options": _TONE_OPTIONS,
        }

    @app.post("/user/tone")
    async def user_set_tone(request: Request) -> dict:
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        body = await request.json()
        tone = str(body.get("tone", "")).strip()
        if tone not in _TONE_VALUES:
            return _json_err(400, f"Invalid tone. Allowed: {', '.join(sorted(_TONE_VALUES))}")
        model_alias = str(body.get("model_alias", getattr(k, "model_alias", "") or getattr(app.state, "model_alias", resolved_settings.model_alias))).strip() or getattr(app.state, "model_alias", resolved_settings.model_alias)
        time_zone = str(body.get("time_zone", getattr(k, "time_zone", "") or getattr(app.state, "time_zone", "Asia/Shanghai"))).strip() or getattr(app.state, "time_zone", "Asia/Shanghai")
        run_permission = str(body.get("run_permission", getattr(k, "run_permission", ""))).strip()
        if run_permission and run_permission not in _RUN_PERMISSIONS:
            return _json_err(400, "Invalid run permission")
        app.state.key_store.update(k.id, tone=tone, model_alias=model_alias, time_zone=time_zone, run_permission=run_permission)
        return {"status": "ok", "tone": tone, "model_alias": model_alias, "time_zone": time_zone, "run_permission": run_permission, "effective_run_permission": _effective_run_permission(app.state.key_store.get(k.id))}

    @app.post("/user/tool-prompt")
    async def user_set_tool_prompt(request: Request) -> dict:
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        body = await request.json()
        prompt = body.get("tool_prompt")
        if not isinstance(prompt, str):
            return _json_err(400, "tool_prompt must be a string")
        app.state.key_store.update(k.id, tool_prompt=prompt[:4000])
        return {"status": "ok", "tool_prompt": prompt[:4000]}

    @app.post("/user/system-prompt")
    async def user_set_system_prompt(request: Request) -> dict:
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        body = await request.json()
        prompt = body.get("system_prompt")
        if not isinstance(prompt, str):
            return _json_err(400, "system_prompt must be a string")
        app.state.key_store.update(k.id, system_prompt=prompt[:8000])
        return {"status": "ok", "system_prompt": prompt[:8000]}

    @app.post("/user/account/token")
    async def user_set_account_token(request: Request) -> dict:
        """Let a user push/update the token for their own bound account.

        If the key has no bound account yet, create one and bind it (self-service
        account provisioning requested for the user UI).
        """
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        body = await request.json()
        token = str(body.get("token", "")).strip()
        if not token:
            return _json_err(400, "Token is empty")
        match = re.search(r"access_token=([^&\s]+)", token)
        token = match.group(1) if match else token
        try:
            claims = decode_jwt_payload(token)
            if not is_substrate_token_claims(claims):
                return _json_err(400, "Token is not a substrate.office.com token")
        except Exception:
            return _json_err(400, "Not a valid JWT token")
        _, email = extract_identity(token)
        # Dedupe by identity: if the pushed token belongs to an M365 account
        # already in the pool, reuse that record instead of creating a duplicate.
        reused = app.state.account_store.find_by_email(email) if email else None
        displaced = 0  # how many other users we bumped off the reused account
        if reused is not None:
            # Take over the shared identity: refresh its token, bind this key,
            # and displace every OTHER key currently pointing at it so those
            # users get a "your account was taken over" notice on their page.
            acc = app.state.account_store.update_token(reused.id, token, token_source="manual")
            now = time.time()
            for other in app.state.key_store.list_for_account(reused.id):
                if other.id == k.id:
                    continue
                app.state.key_store.update(other.id, account_id="", displaced_at=now)
                displaced += 1
            old_acc_id = k.account_id
            app.state.key_store.update(k.id, account_id=reused.id, displaced_at=0.0)
            # Drop the caller's previous account if it is now orphaned (no keys).
            if old_acc_id and old_acc_id != reused.id and not app.state.key_store.list_for_account(old_acc_id):
                app.state.account_store.remove(old_acc_id)
        else:
            acc_id = k.account_id
            if not acc_id or app.state.account_store.get(acc_id) is None:
                acc = app.state.account_store.add(name=k.name or "user", token=token, token_source="manual")
                app.state.key_store.update(k.id, account_id=acc.id, displaced_at=0.0)
            else:
                acc = app.state.account_store.update_token(acc_id, token, token_source="manual")
                if k.displaced_at:
                    app.state.key_store.update(k.id, displaced_at=0.0)
        return {"status": "ok", "token_status": acc.token_status() if acc else None, "displaced": displaced}

    @app.post("/user/account/cookies")
    async def user_set_account_cookies(request: Request) -> dict:
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        if not k.account_id or app.state.account_store.get(k.account_id) is None:
            acc = app.state.account_store.add(name=k.name or k.username or "user", token="", token_source="cdp")
            app.state.key_store.update(k.id, account_id=acc.id, displaced_at=0.0)
            k = app.state.key_store.get(k.id) or k
        body = await request.json()
        cookies = body.get("cookies", [])
        if not isinstance(cookies, list) or not cookies:
            return _json_err(400, "No cookies provided")
        injected, total = await app.state.refresh_scheduler.inject_cookies(k.account_id, cookies)
        if injected != total:
            app.state.account_store.set_cookie_status(k.account_id, False)
            return _json_err(400, f"Cookie injection incomplete: {injected}/{total}")
        acc = app.state.account_store.get(k.account_id)
        if not acc or not acc.cookie_valid:
            return _json_err(400, "Cookie injected, but Microsoft redirected to login. Please sign in to M365 in the browser and push cookies again.")
        return {"status": "ok", "injected": injected, "total": total}

    @app.post("/user/regenerate-key")
    async def user_regenerate_key(request: Request) -> dict:
        """Let a user rotate their own API key. The key id (and thus account
        binding, tone/prompt and session history) is preserved; only the secret
        changes. The browser keeps the new key and re-authenticates with it."""
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        k = app.state.key_store.regenerate_key(k.id)
        return {"status": "ok", "key": k.key if k else None}

    @app.post("/user/account/logout")
    async def user_account_logout(request: Request) -> dict:
        """Sign the user out of Microsoft: wipe the bound account's token/cookie
        state. The account record and key binding are preserved."""
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        if k.account_id and app.state.account_store.get(k.account_id) is not None:
            app.state.account_store.clear_credentials(k.account_id)
        return {"status": "ok"}

    @app.post("/user/account/unbind")
    async def user_account_unbind(request: Request) -> dict:
        """Fully detach the caller's account: unbind the key and, if the account
        is left with no keys pointing at it, remove the record entirely. Use this
        when the user no longer wants the account associated (vs. "登出" which
        wipes token/cookie state but keeps the binding)."""
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        acc_id = k.account_id
        if acc_id and app.state.account_store.get(acc_id) is not None:
            app.state.account_store.clear_credentials(acc_id)
        app.state.key_store.update(k.id, account_id="", displaced_at=0.0)
        removed = False
        if acc_id and not app.state.key_store.list_for_account(acc_id):
            removed = app.state.account_store.remove(acc_id)
        return {"status": "ok", "removed": removed}

    @app.get("/", response_class=HTMLResponse)
    async def user_page(request: Request) -> HTMLResponse:
        # Root is the user-facing page. Admin console moved to /admin.    
        return HTMLResponse(_USER_HTML, headers={"Cache-Control": "no-store"})

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_page(request: Request) -> HTMLResponse:
        if _admin_secret and not _is_admin_authenticated(request):        
            return HTMLResponse(_LOGIN_HTML, headers={"Cache-Control": "no-store"})
        return HTMLResponse(_ADMIN_HTML, headers={"Cache-Control": "no-store"})

    @app.get("/favicon.ico")
    async def favicon():
        from starlette.responses import Response
        return Response(status_code=204)

    def _request_model_alias(raw_request: Request, settings: Settings) -> str:
        key_obj = getattr(raw_request.state, "api_key_obj", None)
        return getattr(key_obj, "model_alias", "") or getattr(app.state, "model_alias", settings.model_alias)

    @app.get("/v1/models")
    async def list_models(raw_request: Request, settings: Settings = Depends(get_settings)) -> dict:
        model_alias = _request_model_alias(raw_request, settings)
        return {
            "object": "list",
            "data": [
                {
                    "id": model_alias,
                    "object": "model",
                    "owned_by": "microsoft-365-copilot",
                },
                {
                    "id": f"{model_alias}{_PERSIST_MODEL_SUFFIX}",
                    "object": "model",
                    "owned_by": "microsoft-365-copilot",
                },
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(
        raw_request: Request,
        request: OpenAIChatRequest,
        settings: Settings = Depends(get_settings),
        client: SubstrateCopilotClient = Depends(get_copilot_client),
    ):
        _log = logging.getLogger("copilot_proxy")
        model_alias = _request_model_alias(raw_request, settings)
        _log.info("[/v1/chat/completions] stream=%s tools=%d messages=%d model=%s",
                  request.stream, len(request.tools) if request.tools else 0,
                  len(request.messages), request.model)
        if request.tools:
            for t in request.tools:
                _log.info("  tool: %s", t.function.name if t.function else "?")
        # Record call for web UI
        call_record = {
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "stream": request.stream,
            "tools": [t.function.name for t in request.tools] if request.tools else [],
            "messages": len(request.messages),
            "model": request.model,
            "tool_calls_result": None,
        }
        try:
            session = _persistent_session(app, raw_request, request.model, request.user, request)
            # Whenever we reuse a persistent M365 session that already has history
            # (both auto mode and explicit :persist mode), the server remembers the
            # prior turns — so only send the incremental turn instead of resending the
            # whole transcript on every request.
            incremental = (
                session is not None
                and session.turn_count > 0
            )
            # Diagnostics: surface in the web call-log so we can see whether the
            # incremental optimization actually kicks in across turns.
            call_record["incremental"] = incremental
            call_record["turn_count"] = session.turn_count if session is not None else None
            _key_obj = getattr(raw_request.state, "api_key_obj", None)
            call_record["tone"] = (_key_obj.tone if _key_obj is not None else getattr(app.state, 'current_tone', 'Magic')) or 'Magic'
            # System prompt: the key's own override wins; if the key hasn't set one,
            # fall back to the global system prompt (admin's "系统提示词（全局）").
            _key_sp = ((_key_obj.system_prompt if _key_obj is not None else "") or "").strip()
            _system_override = _key_sp or getattr(app.state, 'system_prompt', '')
            run_permission = _effective_run_permission(_key_obj)
            read_only_guard = run_permission == "read_only" or _has_read_only_intent(*(flatten_content(m.content) for m in request.messages if m.role == "user"))
            call_record["run_permission"] = run_permission
            call_record["read_only_guard"] = read_only_guard
            translated = translate_openai_request(request, incremental=incremental, system_override=_system_override)
            if request.stream:
                # Save call record for streaming (tool_calls_result resolved later)
                call_record["streaming"] = True
                app.state.call_log.append(call_record)
                if len(app.state.call_log) > 100:
                    app.state.call_log = app.state.call_log[-100:]
                _write_json_list(app.state.call_log_path, app.state.call_log, 100)
                if request.tools:
                    # When tools are present, buffer the full stream then parse tool_calls
                    return StreamingResponse(
                        _openai_stream_with_tools(
                            model_alias,
                            client,
                            translated.prompt,
                            translated.additional_context,
                            session,
                            call_log=app.state.call_log,
                            call_record=call_record,
                            tool_names={t.function.name for t in request.tools if t.function},
                            read_only_guard=read_only_guard,
                        ),
                        media_type="text/event-stream",
                    )
                return StreamingResponse(
                    _openai_stream(
                        model_alias,
                        client,
                        translated.prompt,
                        translated.additional_context,
                        session,
                    ),
                    media_type="text/event-stream",
                )
            text = await client.chat(translated.prompt, translated.additional_context, session)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SubstrateCopilotError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        # If request included tools, parse model output for tool_call blocks
        tool_calls = _extract_tool_calls(text) if request.tools else []
        if read_only_guard and tool_calls:
            blocked = len(tool_calls)
            tool_calls = _filter_read_only_tool_calls(tool_calls)
            if len(tool_calls) != blocked:
                _log.info("  read-only guard filtered mutating tool_call(s)")
        if not tool_calls and request.tools and not read_only_guard:
            # Prose fallback: model described "save as <path>" + code block
            tool_names = {t.function.name for t in request.tools if t.function}
            tool_calls = _extract_prose_write(text, tool_names)
            if tool_calls:
                _log.info("  prose fallback synthesized Write tool_call")
        # Corrective retry: M365 sometimes "creates" a file via its native
        # attachment feature (hosted URL) instead of a tool_call. If it claims a
        # file but emitted none, force one retry demanding a real tool_call.
        if not tool_calls and request.tools and not read_only_guard and _looks_like_fake_file_claim(text):
            _log.info("  fake file claim detected, forcing corrective retry")
            try:
                retry_text = await client.chat(_RETRY_INSTRUCTION, translated.additional_context, session)
                retry_calls = _extract_tool_calls(retry_text)
                if not retry_calls:
                    tool_names = {t.function.name for t in request.tools if t.function}
                    retry_calls = _extract_prose_write(retry_text, tool_names)
                if retry_calls:
                    _log.info("  retry produced %d tool_call(s)", len(retry_calls))
                    text, tool_calls = retry_text, retry_calls
                    call_record["retried"] = True
            except SubstrateCopilotError:
                pass  # Keep original response if retry fails
        _log.info("[/v1/chat/completions] response len=%d tool_calls=%d", len(text), len(tool_calls))
        if tool_calls:
            _log.info("  parsed tool_calls: %s", [tc["function"]["name"] for tc in tool_calls])
        # Save call record
        call_record["response_len"] = len(text)
        call_record["response_text"] = text[:8000]
        call_record["response_repr"] = repr(text[:2000])
        call_record["tool_calls_result"] = [tc["function"]["name"] for tc in tool_calls] if tool_calls else []
        app.state.call_log.append(call_record)
        if len(app.state.call_log) > 100:
            app.state.call_log = app.state.call_log[-100:]
        _write_json_list(app.state.call_log_path, app.state.call_log, 100)
        if tool_calls:
            remaining = _strip_tool_call_blocks(text)
            msg = {"role": "assistant", "content": remaining or None, "tool_calls": tool_calls}
            return JSONResponse({
                "id": f"chatcmpl_{uuid.uuid4().hex}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_alias,
                "choices": [
                    {
                        "index": 0,
                        "message": msg,
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })

        return JSONResponse({
            "id": f"chatcmpl_{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_alias,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    @app.post("/v1/responses")
    async def openai_responses(
        raw: Request,
        settings: Settings = Depends(get_settings),
        client: SubstrateCopilotClient = Depends(get_copilot_client),
    ):
        model_alias = _request_model_alias(raw, settings)
        body = await raw.json()
        try:
            request = OpenAIResponsesRequest.model_validate(body)
            translated = translate_responses_request(request)
            session = _persistent_session(app, raw, request.model, _responses_session_key(request))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if request.stream:
            return StreamingResponse(
                _responses_stream(model_alias, client, translated.prompt, translated.additional_context, session),
                media_type="text/event-stream",
            )

        try:
            text = await client.chat(translated.prompt, translated.additional_context, session)
        except SubstrateCopilotError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return JSONResponse({
            "id": f"resp_{uuid.uuid4().hex}",
            "object": "response",
            "created_at": int(time.time()),
            "model": model_alias,
            "output": [{
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex}",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        })

    @app.post("/v1/messages")
    async def anthropic_messages(
        raw_request: Request,
        request: AnthropicMessagesRequest,
        settings: Settings = Depends(get_settings),
        client: SubstrateCopilotClient = Depends(get_copilot_client),
    ):
        model_alias = _request_model_alias(raw_request, settings)
        try:
            translated = translate_anthropic_request(request)
            session = _persistent_session(app, raw_request, request.model, _messages_session_key(request), request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if request.stream:
            return StreamingResponse(
                _anthropic_stream(model_alias, client, translated.prompt, translated.additional_context, session),
                media_type="text/event-stream",
            )

        try:
            text = await client.chat(translated.prompt, translated.additional_context, session)
        except SubstrateCopilotError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return JSONResponse({
            "id": f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "model": model_alias,
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        })

    return app


def _responses_session_key(request: OpenAIResponsesRequest) -> str | None:
    user = getattr(request, "user", None)
    if isinstance(user, str) and user.strip():
        return user.strip()
    text = json.dumps(request.input, ensure_ascii=False, sort_keys=True)
    if text:
        return "responses_" + hashlib.sha256(text.encode()).hexdigest()[:12]
    return None


def _messages_session_key(request: AnthropicMessagesRequest) -> str | None:
    for msg in request.messages:
        if msg.role == "user":
            text = flatten_content(msg.content).strip()
            if text:
                return "messages_" + hashlib.sha256(text.encode()).hexdigest()[:12]
    return None


def _persistent_session(
    app: FastAPI,
    raw_request: Request,
    model: str,
    fallback_key: str | None = None,
    request: OpenAIChatRequest | AnthropicMessagesRequest | None = None,
) -> PersistentSession | None:
    # Multi-tenant: prefix every session key with the caller's key id (fallback to
    # the bound account id) so two different API keys never share an M365 thread,
    # even when their session ids / opening messages collide.
    key_obj = getattr(raw_request.state, "api_key_obj", None)
    account = getattr(raw_request.state, "account", None)
    tenant = (key_obj.id if key_obj is not None else None) or (account.id if account is not None else "global")
    header_key = (raw_request.headers.get(_SESSION_ID_HEADER) or "").strip()
    if header_key:
        return app.state.session_store.get(f"{tenant}:header:{header_key}")
    if model.endswith(_PERSIST_MODEL_SUFFIX):
        return app.state.session_store.get(f"{tenant}:model:{fallback_key or 'default'}")
    # Auto-detect conversation from the request messages so that all turns of the
    # same Trae conversation reuse one M365 Copilot session (instead of creating a
    # brand-new chat record on every request). A new Trae conversation has a
    # different first user message -> different session key -> new M365 session.
    if request is not None:
        sid, _title = _detect_conversation_session(request)
        # A conversation's opening turn carries no assistant reply yet. If two
        # different conversations happen to share the same first user message
        # (e.g. the same prompt reused to start a new chat), their auto key
        # collides. Reusing the stale M365 thread would feed the model wrong
        # context and make it hallucinate. So on an opening turn, start fresh.
        has_assistant = any(m.role == "assistant" for m in request.messages)
        if not has_assistant:
            return app.state.session_store.reset(f"{tenant}:auto:{sid}")
        return app.state.session_store.get(f"{tenant}:auto:{sid}")
    if fallback_key:
        return app.state.session_store.get(f"{tenant}:auto:{fallback_key}")
    return None


async def _openai_stream(
    model_alias: str,
    client: SubstrateCopilotClient,
    prompt: str,
    additional_context: list[str],
    session: PersistentSession | None = None,
) -> AsyncIterator[str]:
    completion_id = f"chatcmpl_{uuid.uuid4().hex}"
    created = int(time.time())
    first_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_alias,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(first_chunk)}\n\n"
    try:
        async for delta in client.chat_stream(prompt, additional_context, session):
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_alias,
                "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
    except SubstrateCopilotError as exc:
        yield f"data: {json.dumps({'error': {'message': str(exc), 'type': 'upstream_error'}})}\n\n"
        yield "data: [DONE]\n\n"
        return
    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_alias,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"


async def _openai_stream_with_tools(
    model_alias: str,
    client: SubstrateCopilotClient,
    prompt: str,
    additional_context: list[str],
    session: PersistentSession | None = None,
    call_log: list | None = None,
    call_record: dict | None = None,
    tool_names: set | None = None,
    read_only_guard: bool = False,
) -> AsyncIterator[str]:
    """Buffer full stream, then emit as tool_calls if found, else normal content stream."""
    _log = logging.getLogger("copilot_proxy")
    chunks: list[str] = []
    async for delta in client.chat_stream(prompt, additional_context, session):
        chunks.append(delta)
    full_text = "".join(chunks)

    tool_calls = _extract_tool_calls(full_text)
    if read_only_guard and tool_calls:
        blocked = len(tool_calls)
        tool_calls = _filter_read_only_tool_calls(tool_calls)
        if len(tool_calls) != blocked:
            _log.info("  read-only guard filtered mutating tool_call(s)")
    if not tool_calls and tool_names and not read_only_guard:
        # Prose fallback: model described "save as <path>" + code block
        tool_calls = _extract_prose_write(full_text, tool_names)
        if tool_calls:
            _log.info("  prose fallback synthesized Write tool_call")
    # Corrective retry: M365 native file-gen (hosted URL) instead of a tool_call.
    if not tool_calls and tool_names and not read_only_guard and _looks_like_fake_file_claim(full_text):
        _log.info("  fake file claim detected, forcing corrective retry")
        try:
            retry_chunks: list[str] = []
            async for delta in client.chat_stream(_RETRY_INSTRUCTION, additional_context, session):
                retry_chunks.append(delta)
            retry_text = "".join(retry_chunks)
            retry_calls = _extract_tool_calls(retry_text)
            if not retry_calls:
                retry_calls = _extract_prose_write(retry_text, tool_names)
            if retry_calls:
                _log.info("  retry produced %d tool_call(s)", len(retry_calls))
                full_text, tool_calls = retry_text, retry_calls
                if call_record is not None:
                    call_record["retried"] = True
        except SubstrateCopilotError:
            pass  # Keep original response if retry fails
    _log.info("[stream_with_tools] full_text len=%d tool_calls=%d", len(full_text), len(tool_calls))
    if tool_calls:
        _log.info("  parsed tool_calls: %s", [tc["function"]["name"] for tc in tool_calls])
    # Update call record with results
    if call_record is not None:
        call_record["response_len"] = len(full_text)
        call_record["response_text"] = full_text[:8000]
        call_record["response_repr"] = repr(full_text[:2000])
        call_record["tool_calls_result"] = [tc["function"]["name"] for tc in tool_calls] if tool_calls else []
    completion_id = f"chatcmpl_{uuid.uuid4().hex}"
    created = int(time.time())

    if tool_calls:
        remaining = _strip_tool_call_blocks(full_text)
        # Emit role chunk
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"
        # Emit remaining text content if any
        if remaining:
            yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'content': remaining}, 'finish_reason': None}]})}\n\n"
        # Emit tool_calls chunks — one per tool call
        for i, tc in enumerate(tool_calls):
            delta_tc = [{"index": i, "id": tc["id"], "type": "function", "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}]
            yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'tool_calls': delta_tc}, 'finish_reason': None}]})}\n\n"
        # Final chunk with finish_reason
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})}\n\n"
        yield "data: [DONE]\n\n"
    else:
        # No tool calls found — re-stream as normal content
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {'content': full_text}, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_alias, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"


async def _responses_stream(
    model_alias: str,
    client: SubstrateCopilotClient,
    prompt: str,
    additional_context: list[str],
    session: PersistentSession | None = None,
) -> AsyncIterator[str]:
    resp_id = f"resp_{uuid.uuid4().hex}"
    item_id = f"msg_{uuid.uuid4().hex}"
    created = int(time.time())

    yield f"data: {json.dumps({'type': 'response.created', 'response': {'id': resp_id, 'object': 'response', 'created_at': created, 'model': model_alias, 'status': 'in_progress', 'output': []}})}\n\n"
    yield f"data: {json.dumps({'type': 'response.output_item.added', 'output_index': 0, 'item': {'id': item_id, 'type': 'message', 'role': 'assistant', 'content': []}})}\n\n"
    yield f"data: {json.dumps({'type': 'response.content_part.added', 'item_id': item_id, 'output_index': 0, 'content_index': 0, 'part': {'type': 'output_text', 'text': ''}})}\n\n"

    full_text = ""
    try:
        async for delta in client.chat_stream(prompt, additional_context, session):
            full_text += delta
            yield f"data: {json.dumps({'type': 'response.output_text.delta', 'item_id': item_id, 'output_index': 0, 'content_index': 0, 'delta': delta})}\n\n"
    except SubstrateCopilotError as exc:
        yield f"data: {json.dumps({'type': 'error', 'error': {'message': str(exc), 'type': 'upstream_error'}})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'response.output_text.done', 'item_id': item_id, 'output_index': 0, 'content_index': 0, 'text': full_text})}\n\n"
    yield f"data: {json.dumps({'type': 'response.completed', 'response': {'id': resp_id, 'object': 'response', 'created_at': created, 'model': model_alias, 'status': 'completed', 'output': [{'id': item_id, 'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': full_text}]}], 'usage': {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}}})}\n\n"


async def _anthropic_stream(
    model_alias: str,
    client: SubstrateCopilotClient,
    prompt: str,
    additional_context: list[str],
    session: PersistentSession | None = None,
) -> AsyncIterator[str]:
    msg_id = f"msg_{uuid.uuid4().hex}"

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    yield sse("message_start", {"type": "message_start", "message": {"id": msg_id, "type": "message", "role": "assistant", "content": [], "model": model_alias, "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}})
    yield sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
    yield sse("ping", {"type": "ping"})

    try:
        async for delta in client.chat_stream(prompt, additional_context, session):
            yield sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": delta}})
    except SubstrateCopilotError as exc:
        yield sse("error", {"type": "error", "error": {"type": "upstream_error", "message": str(exc)}})
        return

    yield sse("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 0}})
    yield sse("message_stop", {"type": "message_stop"})


_GLASS_SELECT_CSS = """select.glass-native{position:absolute!important;opacity:0!important;pointer-events:none!important;width:1px!important;height:1px!important;margin:0!important;padding:0!important}
.glass-select{position:relative;display:inline-block;min-width:120px;vertical-align:middle;z-index:20}
.glass-select.open{z-index:80}
.tone-select+.glass-select{min-width:180px}
.glass-select-trigger{width:100%;min-height:30px;margin:0!important;padding:.42rem 2rem .42rem .7rem!important;border-radius:12px!important;color:var(--strong)!important;text-align:left!important;background:linear-gradient(135deg,rgba(255,255,255,.13),rgba(96,242,255,.08),rgba(140,107,255,.08))!important;border:1px solid rgba(96,242,255,.28)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.2),0 8px 20px rgba(0,0,0,.12)!important;backdrop-filter:blur(14px);position:relative;overflow:hidden;transition:none!important}
.glass-select-trigger:after{content:"";position:absolute;right:.72rem;top:50%;width:.46rem;height:.46rem;border-right:2px solid var(--cyan);border-bottom:2px solid var(--cyan);transform:translateY(-65%) rotate(45deg);opacity:.9}
.glass-select.open .glass-select-trigger{border-color:rgba(96,242,255,.58)!important;box-shadow:0 0 0 2px rgba(96,242,255,.12),0 0 20px rgba(96,242,255,.18),inset 0 1px 0 rgba(255,255,255,.24)!important}
.glass-select-menu{position:absolute;left:0;right:auto;top:calc(100% + 6px);min-width:100%;width:max-content;max-width:min(360px,calc(100vw - 32px));max-height:260px;overflow:auto;border-radius:14px;padding:.28rem;background:linear-gradient(180deg,rgba(13,19,45,.82),rgba(7,11,27,.78));border:1px solid rgba(96,242,255,.28);box-shadow:0 18px 44px rgba(0,0,0,.38),inset 0 1px 0 rgba(255,255,255,.12);backdrop-filter:blur(22px) saturate(145%);display:none}
.tone-select+.glass-select .glass-select-menu{left:auto;right:0}
.glass-select.open .glass-select-menu{display:block}
.glass-select-menu:before{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;background:linear-gradient(90deg,var(--cyan),var(--violet),var(--pink),var(--gold),var(--cyan));background-size:260% 100%;animation:flowBorder 2.2s linear infinite;-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none;opacity:.75}
.glass-select-option{position:relative;width:100%;margin:0!important;padding:.48rem .62rem!important;border-radius:10px!important;background:transparent!important;color:var(--muted)!important;box-shadow:none!important;text-align:left!important;font-size:.82rem!important;line-height:1.2!important;transition:none!important}
.glass-select-option:hover{background:linear-gradient(135deg,rgba(96,242,255,.18),rgba(140,107,255,.13))!important;color:var(--text)!important;transform:none!important}
.glass-select-option.active{color:var(--text)!important;background:linear-gradient(135deg,rgba(96,242,255,.24),rgba(255,94,219,.12))!important;box-shadow:inset 3px 0 0 rgba(96,242,255,.82)!important}
body[data-theme="light"] .glass-select-trigger{color:#243049!important;background:linear-gradient(135deg,rgba(255,255,255,.84),rgba(96,180,242,.13),rgba(124,58,237,.1))!important;border-color:rgba(14,116,144,.24)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.86),0 8px 18px rgba(47,61,116,.08)!important}
body[data-theme="light"] .glass-select-menu{background:linear-gradient(180deg,rgba(255,255,255,.92),rgba(242,247,255,.88));border-color:rgba(14,116,144,.22);box-shadow:0 18px 38px rgba(80,100,160,.16),inset 0 1px 0 rgba(255,255,255,.86)}
body[data-theme="light"] .glass-select-option{color:#5b6785!important}
body[data-theme="light"] .glass-select-option:hover,body[data-theme="light"] .glass-select-option.active{color:#243049!important}"""

_GLASS_SELECT_JS = """function initGlassSelect(root){
  const scope=root||document;
  scope.querySelectorAll('select').forEach(sel=>{
    if(sel.dataset.glassReady==='1')return;
    sel.dataset.glassReady='1';sel.classList.add('glass-native');
    const wrap=document.createElement('span');wrap.className='glass-select';
    if(sel.classList.contains('page-select'))wrap.style.minWidth='76px';
    if(sel.classList.contains('tone-select'))wrap.style.minWidth='180px';
    if(sel.id==='rebind-select')wrap.style.width='100%';
    const trigger=document.createElement('button');trigger.type='button';trigger.className='glass-select-trigger';
    const menu=document.createElement('div');menu.className='glass-select-menu';
    wrap.appendChild(trigger);wrap.appendChild(menu);sel.parentNode.insertBefore(wrap,sel.nextSibling);
    const close=()=>wrap.classList.remove('open');
    const render=()=>{
      const opt=sel.options[sel.selectedIndex];trigger.textContent=opt?opt.textContent:'';menu.innerHTML='';
      Array.from(sel.options).forEach(o=>{const b=document.createElement('button');b.type='button';b.className='glass-select-option'+(o.value===sel.value?' active':'');b.textContent=o.textContent;b.onclick=e=>{e.stopPropagation();sel.value=o.value;sel.dispatchEvent(new Event('change',{bubbles:true}));render();close()};menu.appendChild(b)});
    };
    sel._glassRender=render;
    trigger.onclick=e=>{e.stopPropagation();document.querySelectorAll('.glass-select.open').forEach(x=>{if(x!==wrap)x.classList.remove('open')});render();wrap.classList.toggle('open')};
    sel.addEventListener('change',render);render();
  });
}
function refreshGlassSelect(sel){
  if(!sel)return;
  if(sel.dataset.glassReady!=='1')initGlassSelect(sel.parentElement||document);
  if(typeof sel._glassRender==='function')sel._glassRender();
}
document.addEventListener('click',()=>document.querySelectorAll('.glass-select.open').forEach(x=>x.classList.remove('open')));
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('.glass-select.open').forEach(x=>x.classList.remove('open'))});"""
