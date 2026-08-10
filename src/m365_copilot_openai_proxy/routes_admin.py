from __future__ import annotations

import re
import secrets
from collections.abc import Callable

from fastapi import FastAPI, Request

from .account_serializers import account_public
from .auth_helpers import _validate_password, _validate_username
from .key_store import ApiKey
from .response_helpers import _json_err
from .runtime_settings import _RUN_PERMISSIONS
from .token_store import decode_jwt_payload, is_substrate_token_claims


def register_admin_account_key_routes(app: FastAPI, require_admin: Callable[[Request], object | None], tone_values: set[str]) -> None:
    def _account_public(acc, bound_keys: list[ApiKey] | None = None) -> dict:
        keys = bound_keys if bound_keys is not None else app.state.key_store.list_for_account(acc.id)
        return account_public(acc, keys)

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
            # 0 => inherit the global ceiling, negative => this key is unlimited.
            # Admin-only: exposing it on the user page would let a user lift their
            # own ceiling, which defeats the point of having one.
            "rate_limit_rpm": int(getattr(k, "rate_limit_rpm", 0) or 0),
            "default_rate_limit_rpm": int(dict(getattr(app.state, "runtime_settings", {}) or {}).get("rate_limit_rpm", 0) or 0),
            "username": k.username,
            "password": k.password,
            "has_password": bool(k.password_hash),
            "role": k.role,
            "created_at": k.created_at,
            "updated_at": k.updated_at,
        }

    @app.get("/admin/accounts")
    async def list_accounts(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        keys_by_account: dict[str, list[ApiKey]] = {}
        for k in app.state.key_store.list():
            if k.account_id:
                keys_by_account.setdefault(k.account_id, []).append(k)
        return {"accounts": [_account_public(a, keys_by_account.get(a.id, [])) for a in app.state.account_store.list()]}

    @app.post("/admin/accounts")
    async def add_account(request: Request) -> dict:
        err = require_admin(request)
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
        err = require_admin(request)
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
        acc = app.state.account_store.push_token(acc_id, token)
        if acc is None:
            return _json_err(404, "Account not found")
        return {"status": "ok", "account": _account_public(acc)}

    @app.post("/admin/accounts/{acc_id}/token/clear")
    async def clear_account_token(acc_id: str, request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        acc = app.state.account_store.clear_token(acc_id)
        if acc is None:
            return _json_err(404, "Account not found")
        return {"status": "ok", "account": _account_public(acc)}

    @app.post("/admin/accounts/{acc_id}/rename")
    async def rename_account(acc_id: str, request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        body = await request.json()
        name = str(body.get("name", "")).strip()
        acc = app.state.account_store.rename(acc_id, name)
        if acc is None:
            return _json_err(404, "Account not found")
        return {"status": "ok", "account": _account_public(acc)}

    @app.post("/admin/accounts/{acc_id}/refresh")
    async def refresh_account(acc_id: str, request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        acc = app.state.account_store.get(acc_id)
        if acc is None:
            return _json_err(404, "Account not found")
        try:
            if getattr(acc, "provider", "m365") == "consumer":
                ok = await app.state.refresh_scheduler.refresh_consumer(acc_id)
            else:
                ok = await app.state.refresh_scheduler.ensure_fresh(acc_id, force=True)
        except Exception as exc:
            return _json_err(502, f"Refresh failed: {exc}")
        if not ok and getattr(acc, "provider", "m365") == "consumer":
            return _json_err(502, "Consumer refresh failed; check the server log")
        acc = app.state.account_store.get(acc_id)
        return {"status": "ok", "refreshed": ok, "account": _account_public(acc) if acc else None}

    @app.post("/admin/accounts/{acc_id}/cookie-refresh")
    async def refresh_account_cookie(acc_id: str, request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        acc = app.state.account_store.get(acc_id)
        if acc is None:
            return _json_err(404, "Account not found")
        if getattr(acc, "provider", "m365") == "consumer":
            try:
                ok = await app.state.refresh_scheduler.refresh_consumer(acc_id)
            except Exception as exc:
                return _json_err(502, f"Consumer refresh failed: {exc}")
            if not ok:
                return _json_err(502, "Consumer refresh failed; check the server log")
            acc = app.state.account_store.get(acc_id)
            total = len(list(getattr(acc, "cookies", []) or [])) if acc else 0
            return {
                "status": "ok",
                "provider": "consumer",
                "injected": total,
                "total": total,
                "cookie_valid": bool(acc.cookie_valid) if acc else False,
                "account": _account_public(acc) if acc else None,
            }
        # Re-inject the LAST pushed cookies. ensure_fresh() no-ops for manual
        # accounts (it only drives the CDP token-refresh path), so the cookie
        # button must replay the stored cookie set through inject_cookies to
        # actually launch Chromium and re-establish the session.
        cookies = list(getattr(acc, "cookies", []) or [])
        if not cookies:
            return _json_err(400, "No stored cookies to refresh; push cookies from the browser first")
        try:
            # allow_nudge=True: the admin refresh button must re-mint all three
            # keys (substrate token + media + designer) in this same session and
            # revisit media_seed_url, regardless of whether an RT path exists.
            injected, total = await app.state.refresh_scheduler.inject_cookies(acc_id, cookies, allow_nudge=True)
        except Exception as exc:
            return _json_err(502, f"Cookie refresh failed: {exc}")
        acc = app.state.account_store.get(acc_id)
        return {
            "status": "ok",
            "injected": injected,
            "total": total,
            "cookie_valid": bool(acc.cookie_valid) if acc else False,
            "account": _account_public(acc) if acc else None,
        }

    @app.delete("/admin/accounts/{acc_id}")
    async def remove_account(acc_id: str, request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        if not await app.state.refresh_scheduler.remove_account(acc_id):
            return _json_err(404, "Account not found")
        app.state.key_store.detach_account(acc_id)  # unbind keys that pointed here
        return {"status": "ok"}

    @app.get("/admin/keys")
    async def list_keys(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        return {"keys": [_key_public(k) for k in app.state.key_store.list()]}

    @app.post("/admin/keys")
    async def add_key(request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        body = await request.json()
        name = str(body.get("name", "")).strip()
        account_id = str(body.get("account_id", "")).strip()
        # New keys inherit the global default tone (admin's "对话模式（默认）")
        # unless an explicit tone is provided; the user can override it later.
        tone = str(body.get("tone", "")).strip() or getattr(app.state, 'current_tone', 'Magic')
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        allowed_tones = {o["value"] for o in (getattr(app.state, "tone_options", None) or [])} or tone_values
        if tone not in allowed_tones:
            return _json_err(400, f"Invalid tone. Allowed: {', '.join(sorted(allowed_tones))}")
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
        err = require_admin(request)
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
            allowed_tones = {o["value"] for o in (getattr(app.state, "tone_options", None) or [])} or tone_values
            if tone not in allowed_tones:
                return _json_err(400, f"Invalid tone. Allowed: {', '.join(sorted(allowed_tones))}")
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
        if "rate_limit_rpm" in body:
            # 0 => inherit global, negative => unlimited for this key. Both are
            # meaningful, so the value is passed through rather than clamped.
            try:
                fields["rate_limit_rpm"] = int(body["rate_limit_rpm"] or 0)
            except (TypeError, ValueError):
                return _json_err(400, "rate_limit_rpm must be an integer")
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
        err = require_admin(request)
        if err: return err
        k = app.state.key_store.regenerate_key(key_id)
        if k is None:
            return _json_err(404, "Key not found")
        return {"status": "ok", "key": _key_public(k)}

    @app.delete("/admin/keys/{key_id}")
    async def remove_key(key_id: str, request: Request) -> dict:
        err = require_admin(request)
        if err: return err
        if not app.state.key_store.remove(key_id):
            return _json_err(404, "Key not found")
        return {"status": "ok"}
