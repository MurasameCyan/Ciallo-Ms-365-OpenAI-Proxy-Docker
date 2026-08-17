"""Admin endpoints for the interactive PKCE login and RT-derived media tokens.

Kept out of ``routes_admin_token`` because that module returns early when the
shared admin CDP browser is disabled -- and the entire point of these endpoints
is to work without a browser.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Request

from .pkce_login import (
    PkceLogins,
    describe_token,
    exchange_code,
    parse_callback,
)
from .refresh_via_rt import (
    M365_DESIGNER_SCOPE,
    M365_MEDIA_SCOPE,
    M365_NATIVE_CLIENT_ID,
    mint_scoped_token,
    normalize_microsoft_id,
)
from .response_helpers import _json_err
from .runtime_flags import ulog
from .token_store import decode_jwt_payload

_SCOPES = {"media": M365_MEDIA_SCOPE, "designer": M365_DESIGNER_SCOPE}


def _logins(app: FastAPI) -> PkceLogins:
    store = getattr(app.state, "pkce_logins", None)
    if store is None:
        store = PkceLogins()
        app.state.pkce_logins = store
    return store


def _m365_account(app: FastAPI, account_id: str):
    account = app.state.account_store.get(account_id) if account_id else None
    if account is None:
        return None, _json_err(404, "Account not found")
    if getattr(account, "provider", "m365") != "m365":
        return None, _json_err(400, "PKCE login only applies to M365 accounts")
    return account, None


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - a malformed body is a 400, not a 500
        return {}
    return body if isinstance(body, dict) else {}


def register_admin_pkce_routes(
    app: FastAPI, require_admin: Callable[[Request], object | None]
) -> None:
    @app.post("/admin/pkce/start")
    async def pkce_start(request: Request) -> dict:
        err = require_admin(request)
        if err:
            return err
        body = await _body(request)
        account, err = _m365_account(app, str(body.get("account_id", "") or "").strip())
        if err:
            return err
        # Sign in against the account's own tenant when we know it: /common works
        # but shows a tenant picker, and a guest identity could pick the wrong one.
        authority = normalize_microsoft_id(
            getattr(account, "refresh_token_tenant_id", "")
        ) or _tenant_of(account) or "common"
        try:
            started = _logins(app).start(
                account.id, authority=authority, login_hint=account.email or ""
            )
        except RuntimeError as exc:
            return _json_err(429, str(exc))
        ulog(f"PKCE login started for {account.id} (authority={authority})")
        return {"status": "ok", **started}

    @app.post("/admin/pkce/complete")
    async def pkce_complete(request: Request) -> dict:
        err = require_admin(request)
        if err:
            return err
        body = await _body(request)
        code, state, parse_error = parse_callback(str(body.get("callback_url", "") or ""))
        if parse_error:
            return _json_err(400, f"Could not read the sign-in redirect: {parse_error}")
        logins = _logins(app)
        # AAD echoes state back, so normally we consume that exact entry. A
        # pasted bare code has none: fall back to the single outstanding login.
        pending = logins.take(state) if state else logins.only_pending()
        if pending is None:
            return _json_err(
                400,
                "No matching sign-in is in progress. Click Start again "
                "(a login expires after 15 minutes and is single-use).",
            )
        if not state:
            logins.take(pending["state"])
        account, err = _m365_account(app, pending["account_id"])
        if err:
            return err
        payload, exchange_error = await exchange_code(
            authority=pending["authority"], code=code, verifier=pending["verifier"]
        )
        if exchange_error:
            return _json_err(502, f"Token exchange failed: {exchange_error}")
        access_token = str(payload.get("access_token", "") or "")
        refresh_token = str(payload.get("refresh_token", "") or "")
        info, describe_error = describe_token(access_token)
        if describe_error:
            return _json_err(502, f"Token rejected: {describe_error}")
        if not refresh_token:
            return _json_err(
                502,
                "Sign-in returned no refresh token, so it cannot keep the account "
                "alive. The client may have lost its offline_access consent.",
            )
        # Never let a login for one person overwrite another person's account.
        current = _subject_of(account)
        if current and current != (info["tenant_id"], info["object_id"]):
            return _json_err(
                409,
                "That sign-in is a different Microsoft identity than this account "
                "is bound to. Sign in as "
                f"{account.email or 'the bound account'} or add a new account.",
            )
        # push_token backfills name/email from the token's own claims.
        app.state.account_store.push_token(account.id, access_token)
        app.state.account_store.set_refresh_token(
            account.id,
            refresh_token,
            client_id=M365_NATIVE_CLIENT_ID,
            authority=info["authority"],
            tenant_id=info["tenant_id"],
            object_id=info["object_id"],
        )
        ulog(
            f"PKCE login completed for {account.id}: substrate token + sliding "
            f"refresh token stored (appid={info['app_id']}, email={info['email']})"
        )
        return {
            "status": "ok",
            "account_id": account.id,
            "email": info["email"],
            "app_id": info["app_id"],
            "expires_at": info["expires_at"],
            "has_refresh_token": True,
        }

    @app.post("/admin/pkce/mint")
    async def pkce_mint(request: Request) -> dict:
        """Mint a media/designer token from the stored RT and persist it.

        This is the browser-free replacement for the CDP media capture: same
        refresh token, different audience. Also the honest way to check whether a
        given account's client is actually allowed to ask for that audience.
        """
        err = require_admin(request)
        if err:
            return err
        body = await _body(request)
        kind = str(body.get("kind", "") or "").strip().lower()
        if kind not in _SCOPES:
            return _json_err(400, "kind must be 'media' or 'designer'")
        account, err = _m365_account(app, str(body.get("account_id", "") or "").strip())
        if err:
            return err
        token, mint_error = await mint_scoped_token(
            app.state.account_store, account.id, _SCOPES[kind]
        )
        if mint_error:
            return _json_err(502, f"Could not mint the {kind} token: {mint_error}")
        if kind == "media":
            app.state.account_store.set_media_auth_token(account.id, token)
        else:
            app.state.account_store.set_designer_auth_token(account.id, token)
        ulog(f"Minted {kind} token for {account.id} from the stored refresh token")
        return {"status": "ok", "kind": kind, "scope": _SCOPES[kind], **_token_shape(token)}


def _token_shape(token: str) -> dict:
    """Describe a minted token without ever returning it to the browser."""
    try:
        claims = decode_jwt_payload(token)
    except Exception:  # noqa: BLE001 - Designer returns an opaque JWE
        return {"format": "opaque", "length": len(token)}
    return {
        "format": "jwt",
        "aud": str(claims.get("aud", "") or ""),
        "app_id": str(claims.get("appid", "") or ""),
        "expires_at": int(claims.get("exp", 0) or 0),
    }


def _subject_of(account) -> tuple[str, str] | None:
    try:
        claims = decode_jwt_payload(getattr(account, "token", "") or "")
    except Exception:  # noqa: BLE001 - no usable token means nothing to conflict with
        return None
    tenant_id = normalize_microsoft_id(claims.get("tid"))
    object_id = normalize_microsoft_id(claims.get("oid"))
    return (tenant_id, object_id) if tenant_id and object_id else None


def _tenant_of(account) -> str:
    subject = _subject_of(account)
    return subject[0] if subject else ""
