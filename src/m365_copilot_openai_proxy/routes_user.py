from __future__ import annotations

import asyncio
import re
import time

from fastapi import FastAPI, Request

from .account_serializers import account_binding_state, user_account_public
from .auth_helpers import _validate_password
from .account_store import extract_identity
from .config import Settings
from .key_store import ApiKey
from .response_helpers import _json_err
from .runtime_settings import _RUN_PERMISSIONS, normalize_media_proxy_suffixes
from .token_store import decode_jwt_payload, is_substrate_token_claims
from .translator import default_tool_system_prompt

# Keep strong references to fire-and-forget background tasks so the event loop
# does not garbage-collect them mid-flight (see asyncio.create_task docs).
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn_post_push_refresh(scheduler, account_id: str) -> None:
    """After a successful cookie injection, capture a substrate token in the
    background so the account gets a real token + a positive cookie_expires_at.

    Without this the account can sit at cookie_expires_at=0, which _keepalive_due
    treats as "no signal" and never auto-refreshes, so the session silently dies
    once the cookie expires. Runs detached: the push response returns immediately
    and the token/expiry appear on the next admin refresh (~10-20s later).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _run() -> None:
        try:
            # force=False on purpose: if inject_cookies already captured a token
            # opportunistically in the same session, the token is fresh and this
            # becomes a cheap no-op (no second Chromium launch). It only spins up
            # a real refresh (with nudge) when the opportunistic grab did not land
            # a usable token.
            await scheduler.ensure_fresh(account_id, force=False)
        except Exception as exc:  # noqa: BLE001 - detached task must not raise
            print(f"Post-push refresh failed for {account_id}: {exc}", flush=True)

    task = loop.create_task(_run())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def register_user_routes(app: FastAPI, resolved_settings: Settings, tone_options: list[dict]) -> None:
    tone_values = {o["value"] for o in tone_options}

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

    def _effective_run_permission(k: ApiKey | None) -> str:
        value = ((getattr(k, "run_permission", "") if k is not None else "") or "").strip()
        return value if value in _RUN_PERMISSIONS else getattr(app.state, "run_permission", "full")

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
        binding_state = account_binding_state(acc)
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
            "ws_idle_timeout_minutes": int(getattr(k, "ws_idle_timeout_minutes", 0) or 0),
            "default_ws_idle_timeout_minutes": int(getattr(app.state, "ws_idle_timeout_minutes", 0) or 0),
            "media_proxy_suffixes": list(getattr(k, "media_proxy_suffixes", []) or []),
            "default_media_proxy_suffixes": list(dict(getattr(app.state, "runtime_settings", {}) or {}).get("media_proxy_suffixes", []) or []),
            "default_system_prompt": default_tool_system_prompt(),
            "displaced": bool(getattr(k, "displaced_at", 0.0)),
            "displaced_at": getattr(k, "displaced_at", 0.0),
            "binding_state": binding_state,
            "account": user_account_public(acc),
            "tone_options": list(getattr(app.state, "tone_options", None) or tone_options),
        }

    @app.post("/user/tone")
    async def user_set_tone(request: Request) -> dict:
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        body = await request.json()
        tone = str(body.get("tone", "")).strip()
        allowed = {o["value"] for o in (getattr(app.state, "tone_options", None) or tone_options)}
        if tone not in allowed:
            return _json_err(400, f"Invalid tone. Allowed: {', '.join(sorted(allowed))}")
        model_alias = str(body.get("model_alias", getattr(k, "model_alias", "") or getattr(app.state, "model_alias", resolved_settings.model_alias))).strip() or getattr(app.state, "model_alias", resolved_settings.model_alias)
        time_zone = str(body.get("time_zone", getattr(k, "time_zone", "") or getattr(app.state, "time_zone", "Asia/Shanghai"))).strip() or getattr(app.state, "time_zone", "Asia/Shanghai")
        run_permission = str(body.get("run_permission", getattr(k, "run_permission", ""))).strip()
        if run_permission and run_permission not in _RUN_PERMISSIONS:
            return _json_err(400, "Invalid run permission")
        # Per-user media suffix override: empty => inherit global; non-empty =>
        # fully replace the global suffixes for this user's signed media URLs.
        if "media_proxy_suffixes" in body:
            media_proxy_suffixes = normalize_media_proxy_suffixes(body.get("media_proxy_suffixes"))
        else:
            media_proxy_suffixes = list(getattr(k, "media_proxy_suffixes", []) or [])
        # Per-user chat idle timeout (minutes): 0 => inherit global; otherwise >=1.
        if "ws_idle_timeout_minutes" in body:
            try:
                ws_idle_timeout_minutes = int(body.get("ws_idle_timeout_minutes") or 0)
            except (TypeError, ValueError):
                return _json_err(400, "ws_idle_timeout_minutes must be an integer")
            if ws_idle_timeout_minutes < 0:
                ws_idle_timeout_minutes = 0
            if ws_idle_timeout_minutes > 0:
                ws_idle_timeout_minutes = max(1, ws_idle_timeout_minutes)
        else:
            ws_idle_timeout_minutes = int(getattr(k, "ws_idle_timeout_minutes", 0) or 0)
        app.state.key_store.update(k.id, tone=tone, model_alias=model_alias, time_zone=time_zone, run_permission=run_permission, ws_idle_timeout_minutes=ws_idle_timeout_minutes, media_proxy_suffixes=media_proxy_suffixes)
        return {"status": "ok", "tone": tone, "model_alias": model_alias, "time_zone": time_zone, "run_permission": run_permission, "ws_idle_timeout_minutes": ws_idle_timeout_minutes, "media_proxy_suffixes": media_proxy_suffixes, "effective_run_permission": _effective_run_permission(app.state.key_store.get(k.id))}

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

    @app.post("/user/account/media-auth")
    async def user_set_account_media_auth(request: Request) -> dict:
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        if not k.account_id or app.state.account_store.get(k.account_id) is None:
            return _json_err(400, "No bound account")
        body = await request.json()
        host = str(body.get("host", "") or "").strip().lower()
        if host != "teams.microsoft.com" and not host.endswith(".teams.microsoft.com"):
            return _json_err(400, "Unsupported media auth host")
        auth = str(body.get("authorization", "") or "").strip()
        match = re.match(r"^Bearer\s+(.+)$", auth, re.IGNORECASE)
        token = match.group(1).strip() if match else ""
        if not token:
            return _json_err(400, "Media auth token is empty")
        app.state.account_store.set_media_auth_token(k.account_id, token)
        return {"status": "ok", "has_media_auth": True}

    @app.post("/user/account/designer-auth")
    async def user_set_account_designer_auth(request: Request) -> dict:
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        if not k.account_id or app.state.account_store.get(k.account_id) is None:
            return _json_err(400, "No bound account")
        body = await request.json()
        host = str(body.get("host", "") or "").strip().lower()
        if host != "designerapp.officeapps.live.com" and not host.endswith(".officeapps.live.com"):
            return _json_err(400, "Unsupported designer auth host")
        # designerapp sends the Authorization value WITHOUT a "Bearer " prefix (raw
        # JWE); store it verbatim so it can be replayed exactly as the browser sends it.
        token = str(body.get("authorization", "") or "").strip()
        if not token:
            return _json_err(400, "Designer auth token is empty")
        app.state.account_store.set_designer_auth_token(k.account_id, token)
        return {"status": "ok", "has_designer_auth": True}

    @app.post("/user/account/cookies")
    async def user_set_account_cookies(request: Request) -> dict:
        k = _resolve_user_key(request)
        if k is None:
            return _json_err(401, "Invalid API key", "auth_error")
        body = await request.json()
        username = body.get("username")
        account_name = username.strip() if isinstance(username, str) else ""
        cookies = body.get("cookies", [])
        if not isinstance(cookies, list) or not cookies:
            return _json_err(400, "No cookies provided")
        if not k.account_id or app.state.account_store.get(k.account_id) is None:
            acc = app.state.account_store.add(name=account_name or k.name or k.username or "user", token="", token_source="cdp")
            app.state.key_store.update(k.id, account_id=acc.id, displaced_at=0.0)
            k = app.state.key_store.get(k.id) or k
        app.state.account_store.set_cookies(k.account_id, cookies)
        injected, total = await app.state.refresh_scheduler.inject_cookies(k.account_id, cookies)
        acc = app.state.account_store.get(k.account_id)
        warning = ""
        if injected != total:
            app.state.account_store.set_cookie_status(k.account_id, False)
            warning = f"Cookie saved, but Chromium injection incomplete: {injected}/{total}"
        elif not acc or not acc.cookie_valid:
            warning = "Cookie saved, but Microsoft redirected to login. Please sign in to M365 in the browser and push cookies again."
        else:
            # Injection established the session but only sets cookie_expires_at
            # from the cookies' own expiry (often 0 for session cookies). Capture
            # a token in the background so a real token + 12h expiry land now,
            # which is what arms keepalive auto-refresh (see _spawn helper).
            _spawn_post_push_refresh(app.state.refresh_scheduler, k.account_id)
        if account_name and acc and acc.name != account_name:
            app.state.account_store.rename(k.account_id, account_name)
        result = {"status": "ok", "injected": injected, "total": total}
        if warning:
            result["warning"] = warning
        return result

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
