from __future__ import annotations

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
from .account_store import AccountStore
from .key_store import ApiKey, KeyStore
from .refresh_scheduler import RefreshScheduler
from .session_store import PersistentSession, PersistentSessionStore
from .substrate_client import SubstrateCopilotClient, SubstrateCopilotError
from .token_store import AccessTokenStore, read_username, decode_jwt_payload, init_token_dir, read_tone, read_tool_prompt, read_system_prompt
from .models import AnthropicMessagesRequest, OpenAIChatRequest, OpenAIResponsesRequest
from .translator import translate_anthropic_request, translate_openai_request, translate_responses_request, flatten_content
from .templates import _ADMIN_HTML, _LOGIN_HTML, _USER_HTML
from .routes_admin import register_admin_account_key_routes
from .routes_admin_debug import register_admin_debug_routes
from .routes_admin_observability import register_admin_observability_routes
from .routes_admin_settings import register_admin_settings_routes
from .routes_admin_token import register_admin_token_routes
from .routes_user import register_user_routes
from .runtime_settings import (
    _RUN_PERMISSIONS,
    _read_runtime_settings,
)
from .call_log_store import (
    append_call_log,
    load_call_log,
    record_response_text,
)
from .metrics_store import init_metrics_store
from .session_helpers import (
    _PERSIST_MODEL_SUFFIX,
    _SESSION_ID_HEADER,
    _messages_session_key,
    _persistent_session,
    _responses_session_key,
)
from .response_helpers import (
    _anthropic_stream,
    _json_err,
    _openai_stream,
    _responses_stream,
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
    runtime_settings = _read_runtime_settings(resolved_settings.token_dir)
    app.state.call_log_limit = runtime_settings["call_log_limit"]
    app.state.call_log_path = Path(resolved_settings.token_dir) / "call_log.json"
    app.state.call_log: list[dict] = load_call_log(app.state.call_log_path, app.state.call_log_limit)  # API call log for web UI display
    app.state.captured_payloads: list[dict] = []  # Substrate chat payloads captured via get_token.js for mode comparison
    # Metrics time-series for the home dashboard trend chart.
    init_metrics_store(app.state, Path(resolved_settings.token_dir) / "metrics_history.json")
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
        allow_headers=["Content-Type", "Authorization", _SESSION_ID_HEADER],
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
            resp.headers["Access-Control-Allow-Headers"] = f"Content-Type, Authorization, {_SESSION_ID_HEADER}"
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

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "token": app.state.token_store.status()}

    register_admin_token_routes(app, _require_admin)

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

    register_admin_observability_routes(app, _require_admin)

    register_admin_debug_routes(app, _require_admin)

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

    register_admin_settings_routes(app, _require_admin, resolved_settings, _TONE_OPTIONS, _TONE_VALUES)

    # ============================ Multi-tenant admin API ============================
    def _effective_run_permission(k: ApiKey | None) -> str:
        value = ((getattr(k, "run_permission", "") if k is not None else "") or "").strip()
        return value if value in _RUN_PERMISSIONS else getattr(app.state, "run_permission", "full")

    register_admin_account_key_routes(app, _require_admin, _TONE_VALUES)

    register_user_routes(app, resolved_settings, _TONE_OPTIONS)

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
            "api": "chat",
            "endpoint": "/v1/chat/completions",
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
                append_call_log(app.state, call_record)
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
                        on_text_done=lambda text: record_response_text(app.state, call_record, text),
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
        append_call_log(app.state, call_record)
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

        _key_obj = getattr(raw.state, "api_key_obj", None)
        call_record = {
            "api": "responses",
            "endpoint": "/v1/responses",
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "stream": request.stream,
            "tools": [],
            "messages": len(request.input) if isinstance(request.input, list) else 1,
            "model": request.model,
            "tone": (_key_obj.tone if _key_obj is not None else getattr(app.state, 'current_tone', 'Magic')) or 'Magic',
            "tool_calls_result": None if request.stream else [],
        }

        if request.stream:
            call_record["streaming"] = True
            append_call_log(app.state, call_record)
            return StreamingResponse(
                _responses_stream(
                    model_alias,
                    client,
                    translated.prompt,
                    translated.additional_context,
                    session,
                    on_text_done=lambda text: record_response_text(app.state, call_record, text),
                ),
                media_type="text/event-stream",
            )

        try:
            text = await client.chat(translated.prompt, translated.additional_context, session)
        except SubstrateCopilotError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        record_response_text(app.state, call_record, text)
        append_call_log(app.state, call_record)

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

        _key_obj = getattr(raw_request.state, "api_key_obj", None)
        call_record = {
            "api": "anthropic",
            "endpoint": "/v1/messages",
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "stream": request.stream,
            "tools": [],
            "messages": len(request.messages),
            "model": request.model,
            "tone": (_key_obj.tone if _key_obj is not None else getattr(app.state, 'current_tone', 'Magic')) or 'Magic',
            "tool_calls_result": None if request.stream else [],
        }

        if request.stream:
            call_record["streaming"] = True
            append_call_log(app.state, call_record)
            return StreamingResponse(
                _anthropic_stream(
                    model_alias,
                    client,
                    translated.prompt,
                    translated.additional_context,
                    session,
                    on_text_done=lambda text: record_response_text(app.state, call_record, text),
                ),
                media_type="text/event-stream",
            )

        try:
            text = await client.chat(translated.prompt, translated.additional_context, session)
        except SubstrateCopilotError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        record_response_text(app.state, call_record, text)
        append_call_log(app.state, call_record)

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
