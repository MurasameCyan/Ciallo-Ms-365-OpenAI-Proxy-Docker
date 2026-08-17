"""PKCE login and RT-derived media tokens, for the admin page and the user page.

Kept out of ``routes_admin_token`` because that module returns early when the
shared admin CDP browser is disabled -- and the entire point of these endpoints
is to work without a browser.

Two audiences, one implementation (same split as ``routes_sessions``):
  * ``/admin/pkce/*`` names the account in the request body.
  * ``/user/pkce/*`` is pinned to the account the caller's API key is bound to,
    so a user can re-authorise their own credentials without an admin.
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
from .routes_user import resolve_bearer_key
from .runtime_flags import ulog
from .token_store import decode_jwt_payload

_SCOPES = {"media": M365_MEDIA_SCOPE, "designer": M365_DESIGNER_SCOPE}
_NO_LOGIN_IN_PROGRESS = (
    "No matching sign-in is in progress. Click Start again "
    "(a login expires after 15 minutes and is single-use)."
)


def _logins(app: FastAPI) -> PkceLogins:
    store = getattr(app.state, "pkce_logins", None)
    if store is None:
        store = PkceLogins()
        app.state.pkce_logins = store
    return store


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - a malformed body is a 400, not a 500
        return {}
    return body if isinstance(body, dict) else {}


def register_pkce_routes(
    app: FastAPI, require_admin: Callable[[Request], object | None]
) -> None:
    def _m365_account(account_id: str):
        account = app.state.account_store.get(account_id) if account_id else None
        if account is None:
            return None, _json_err(404, "Account not found")
        if getattr(account, "provider", "m365") != "m365":
            return None, _json_err(400, "PKCE login only applies to M365 accounts")
        return account, None

    def _caller_account(request: Request):
        """The M365 account the API key on this request is bound to."""
        key = resolve_bearer_key(app, request)
        if key is None:
            return None, _json_err(401, "Invalid API key", "auth_error")
        if not key.account_id:
            return None, _json_err(400, "No bound account")
        return _m365_account(key.account_id)

    def _kind(body: dict) -> tuple[str, object | None]:
        kind = str(body.get("kind", "") or "").strip().lower()
        if kind not in _SCOPES:
            return "", _json_err(400, "kind must be 'media' or 'designer'")
        return kind, None

    def _start(account):
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

    async def _mint(account_id: str, kind: str) -> tuple[dict, str]:
        """Mint one scoped token off the stored RT and persist it.

        Returns ``(shape, error)``: the token itself never leaves this function.
        """
        token, mint_error = await mint_scoped_token(
            app.state.account_store, account_id, _SCOPES[kind]
        )
        if mint_error:
            return {}, mint_error
        if kind == "media":
            app.state.account_store.set_media_auth_token(account_id, token)
        else:
            app.state.account_store.set_designer_auth_token(account_id, token)
        ulog(f"Minted {kind} token for {account_id} from the stored refresh token")
        return {
            "status": "ok",
            "kind": kind,
            "scope": _SCOPES[kind],
            **_token_shape(token),
        }, ""

    async def _complete(callback_url: str, *, only_account_id: str = ""):
        code, state, parse_error = parse_callback(callback_url)
        if parse_error:
            return _json_err(400, f"Could not read the sign-in redirect: {parse_error}")
        logins = _logins(app)
        # AAD echoes state back, so normally we consume that exact entry. A
        # pasted bare code has none: fall back to the single outstanding login.
        pending = logins.take(state) if state else logins.only_pending()
        # The ownership check comes before only_pending()'s entry is consumed, so
        # a user pasting a bare code can never burn somebody else's login.
        if pending is None or (only_account_id and pending["account_id"] != only_account_id):
            return _json_err(400, _NO_LOGIN_IN_PROGRESS)
        if not state:
            logins.take(pending["state"])
        account, err = _m365_account(pending["account_id"])
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
        # Attachments and image download need their own audiences, and nothing
        # mints those until a media fetch happens to need one -- by which time a
        # request is already failing. They are plain scope hops on the RT we just
        # stored, so take both now. Sequential on purpose: every redemption
        # rotates the RT, so two concurrent hops would lose one rotation.
        media_keys = {}
        for kind in _SCOPES:
            shape, mint_error = await _mint(account.id, kind)
            media_keys[kind] = (
                shape if not mint_error else {"status": "error", "error": mint_error}
            )
        return {
            "status": "ok",
            "account_id": account.id,
            "email": info["email"],
            "app_id": info["app_id"],
            "expires_at": info["expires_at"],
            "has_refresh_token": True,
            # A key that cannot be minted does not undo the sign-in: the account
            # is already usable for chat, just not for media.
            "media_keys": media_keys,
        }

    # ---------------------------------------------------------------- admin
    @app.post("/admin/pkce/start")
    async def admin_pkce_start(request: Request):
        err = require_admin(request)
        if err:
            return err
        body = await _body(request)
        account, err = _m365_account(str(body.get("account_id", "") or "").strip())
        if err:
            return err
        return _start(account)

    @app.post("/admin/pkce/complete")
    async def admin_pkce_complete(request: Request):
        err = require_admin(request)
        if err:
            return err
        body = await _body(request)
        return await _complete(str(body.get("callback_url", "") or ""))

    @app.post("/admin/pkce/mint")
    async def admin_pkce_mint(request: Request):
        """Mint a media/designer token from the stored RT and persist it.

        This is the browser-free replacement for the CDP media capture: same
        refresh token, different audience. Also the honest way to check whether a
        given account's client is actually allowed to ask for that audience.
        """
        err = require_admin(request)
        if err:
            return err
        body = await _body(request)
        kind, err = _kind(body)
        if err:
            return err
        account, err = _m365_account(str(body.get("account_id", "") or "").strip())
        if err:
            return err
        shape, mint_error = await _mint(account.id, kind)
        if mint_error:
            return _json_err(502, f"Could not mint the {kind} token: {mint_error}")
        return shape

    # ----------------------------------------------------------------- user
    @app.post("/user/pkce/start")
    async def user_pkce_start(request: Request):
        account, err = _caller_account(request)
        if err:
            return err
        return _start(account)

    @app.post("/user/pkce/complete")
    async def user_pkce_complete(request: Request):
        account, err = _caller_account(request)
        if err:
            return err
        body = await _body(request)
        return await _complete(
            str(body.get("callback_url", "") or ""), only_account_id=account.id
        )

    @app.post("/user/pkce/mint")
    async def user_pkce_mint(request: Request):
        account, err = _caller_account(request)
        if err:
            return err
        kind, err = _kind(await _body(request))
        if err:
            return err
        shape, mint_error = await _mint(account.id, kind)
        if mint_error:
            return _json_err(502, f"Could not mint the {kind} token: {mint_error}")
        return shape


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
