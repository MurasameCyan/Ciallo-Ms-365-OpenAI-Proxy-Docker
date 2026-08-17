"""Interactive PKCE login for an M365 account (one browser sign-in, no cookies).

Why this exists: every credential the pool holds today comes out of a browser we
have to keep alive. The substrate token is scraped over CDP, its refresh token
(when the userscript pushes one) belongs to the m365.cloud.microsoft SPA and so
expires ~24h after issue no matter how often it is redeemed, and the media and
designer tokens are only captured by watching a real page fetch images. That is
why cookie keepalive, a headless Chromium and a media seed URL all exist.

Authorization code + PKCE against the *native* Office Copilot client removes the
premise: the refresh token it returns is a normal sliding RT, and every other
audience the proxy needs (Teams media, Designer) is a plain scope hop on the same
RT (see ``refresh_via_rt.mint_scoped_token``). One human sign-in, then HTTP only.

The flow is deliberately copy-paste rather than a hosted redirect: the client is
registered with the AAD ``nativeclient`` redirect, so the browser lands on a
Microsoft page whose URL carries ``?code=``. The operator pastes that URL back.
No inbound callback route, no public hostname, no client secret.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from .refresh_via_rt import (
    M365_NATIVE_CLIENT_ID,
    normalize_m365_authority,
    normalize_microsoft_id,
)
from .token_store import decode_jwt_payload, is_substrate_token_claims

# The AAD redirect that renders the code in the address bar instead of posting it
# somewhere. Registered on the native client; nothing listens on it.
NATIVE_REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"
# Ask for the same audience the substrate client uses, plus offline_access so the
# response carries the refresh token this whole exercise is about.
PKCE_SCOPE = (
    "https://substrate.office.com/sydney/.default offline_access openid profile"
)
_AUTHORIZE_URL = "https://login.microsoftonline.com/{authority}/oauth2/v2.0/authorize"
_TOKEN_URL = "https://login.microsoftonline.com/{authority}/oauth2/v2.0/token"
_HTTP_TIMEOUT_SECONDS = 30
# How long a started login may sit unfinished. Long enough for MFA on a phone,
# short enough that a stale verifier is not lying around for a shift.
PENDING_TTL_SECONDS = 15 * 60
# Bound the in-memory pending map so a script hammering /pkce/start cannot grow
# it without limit. ponytail: plain dict + prune, not an LRU -- the real bound is
# the admin session, and 32 concurrent logins is already absurd.
_MAX_PENDING = 32


def make_verifier() -> str:
    """RFC 7636 code_verifier: 43-128 chars of unreserved alphabet."""
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def authorize_url(
    *, authority: str, state: str, verifier: str, login_hint: str = ""
) -> str:
    params = {
        "client_id": M365_NATIVE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": NATIVE_REDIRECT_URI,
        "response_mode": "query",
        "scope": PKCE_SCOPE,
        "state": state,
        "code_challenge": code_challenge(verifier),
        "code_challenge_method": "S256",
        # Force the account picker: a browser already signed in as somebody else
        # would otherwise silently bind the wrong identity to this pool account.
        "prompt": "select_account",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return _AUTHORIZE_URL.format(authority=authority or "common") + "?" + urlencode(params)


def parse_callback(raw: str) -> tuple[str, str, str]:
    """Split a pasted redirect URL into ``(code, state, error)``.

    Accepts the full URL, a bare query string, or just the code -- operators
    paste all three. Only one of code/error is meaningful.
    """
    candidate = (raw or "").strip()
    if not candidate:
        return "", "", "nothing pasted"
    if "?" not in candidate and "=" not in candidate:
        # A bare authorization code. AAD codes are long and opaque; anything
        # short is a paste accident, not a code.
        return (candidate, "", "") if len(candidate) >= 20 else ("", "", "not a callback URL or code")
    query = urlsplit(candidate).query or candidate.lstrip("?")
    parsed = parse_qs(query, keep_blank_values=False)
    if "error" in parsed:
        detail = (parsed.get("error_description") or [""])[0].splitlines()
        return "", "", f"{parsed['error'][0]}: {detail[0] if detail else ''}".strip(": ")
    code = (parsed.get("code") or [""])[0].strip()
    state = (parsed.get("state") or [""])[0].strip()
    if not code:
        return "", state, "callback URL carries no code"
    return code, state, ""


class PkceLogins:
    """In-memory store of started logins, keyed by the OAuth ``state``.

    Not persisted on purpose: a verifier outliving a restart buys nothing (the
    operator just clicks start again) and would be one more secret at rest.
    """

    def __init__(self) -> None:
        self._pending: dict[str, dict] = {}

    def start(self, account_id: str, *, authority: str = "common", login_hint: str = "") -> dict:
        self._prune()
        if len(self._pending) >= _MAX_PENDING:
            raise RuntimeError("too many logins in progress; finish or wait for one to expire")
        state = secrets.token_urlsafe(24)
        verifier = make_verifier()
        self._pending[state] = {
            "account_id": account_id,
            "verifier": verifier,
            "authority": authority or "common",
            "created_at": time.time(),
        }
        return {
            "state": state,
            "authority": authority or "common",
            "auth_url": authorize_url(
                authority=authority, state=state, verifier=verifier, login_hint=login_hint
            ),
            "expires_in": PENDING_TTL_SECONDS,
        }

    def take(self, state: str) -> dict | None:
        """Consume a pending login. One-shot: a code is only redeemable once."""
        self._prune()
        return self._pending.pop(state, None)

    def only_pending(self) -> dict | None:
        """The single outstanding login, if there is exactly one.

        AAD echoes ``state`` back, so this is a fallback for the case where the
        operator pasted a bare code with no query string.
        """
        self._prune()
        if len(self._pending) != 1:
            return None
        state = next(iter(self._pending))
        entry = dict(self._pending[state])
        entry["state"] = state
        return entry

    def _prune(self) -> None:
        cutoff = time.time() - PENDING_TTL_SECONDS
        for state in [s for s, e in self._pending.items() if e["created_at"] < cutoff]:
            self._pending.pop(state, None)


async def exchange_code(*, authority: str, code: str, verifier: str) -> tuple[dict, str]:
    """Redeem an authorization code. Returns ``(payload, error)``.

    No Origin header: this is a native public client, and AAD would otherwise
    apply single-page-app rules and cap the refresh token at ~24h -- the exact
    limitation this login exists to escape.
    """
    import httpx

    data = {
        "client_id": M365_NATIVE_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": NATIVE_REDIRECT_URI,
        "scope": PKCE_SCOPE,
        "code_verifier": verifier,
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                _TOKEN_URL.format(authority=authority or "common"),
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator verbatim
        return {}, f"HTTP error: {exc}"
    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {}, f"cannot parse token response: {exc}"
    if resp.status_code != 200:
        desc = str(payload.get("error_description", "") or "").splitlines()
        return {}, (
            f"HTTP {resp.status_code} {payload.get('error', '')}: "
            f"{desc[0] if desc else ''}"
        ).strip(": ")
    return payload, ""


def describe_token(access_token: str) -> tuple[dict, str]:
    """Validate a PKCE access token and pull out the identity we must bind to.

    Returns ``(info, error)`` where info carries tenant_id/object_id/email/exp.
    A token for the wrong audience is rejected here rather than being written to
    the pool and failing on the next real turn.
    """
    try:
        claims = decode_jwt_payload(access_token)
    except Exception as exc:  # noqa: BLE001
        return {}, f"access_token is not a JWT: {exc}"
    if not is_substrate_token_claims(claims):
        return {}, f"token aud={claims.get('aud')!r} is not a substrate token"
    tenant_id = normalize_microsoft_id(claims.get("tid"))
    object_id = normalize_microsoft_id(claims.get("oid"))
    if not tenant_id or not object_id:
        return {}, "token has no usable tid/oid to bind the refresh token to"
    return {
        "tenant_id": tenant_id,
        "object_id": object_id,
        "authority": normalize_m365_authority(tenant_id) or "common",
        "email": str(
            claims.get("upn") or claims.get("preferred_username") or claims.get("unique_name") or ""
        ),
        "expires_at": int(claims.get("exp", 0) or 0),
        "app_id": str(claims.get("appid", "") or ""),
    }, ""
