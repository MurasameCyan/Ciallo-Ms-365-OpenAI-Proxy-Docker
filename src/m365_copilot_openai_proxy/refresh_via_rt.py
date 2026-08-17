"""HTTP refresh_token -> substrate access token exchange (no browser).

This is the fast refresh path proven by the POC: the userscript captures the
OAuth2 refresh_token from the M365 token response and pushes it to the server;
here we exchange it for a fresh substrate access token over plain HTTP, with no
headless Chromium involved.

Recipe (validated against a real account):
    POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
    Content-Type: application/x-www-form-urlencoded
    Origin: https://m365.cloud.microsoft
    client_id     = 4765445b-32c6-49b0-83e6-1d93765276ca   (the Copilot client)
    grant_type    = refresh_token
    refresh_token = <RT>
    scope         = https://substrate.office.com/sydney/.default openid profile offline_access

The response may carry a rotated refresh_token, but SPA RTs retain the original
absolute lifetime (normally about 24 hours), so for the SPA client CDP remains
the long-term session renewal path.

Two clients can issue the RT we store, and the difference matters:

* ``4765445b`` is the m365.cloud.microsoft SPA. AAD applies SPA rules (fixed
  ~24h absolute RT lifetime, redemption must look cross-origin), which is why an
  SPA-only deployment still needs cookies/CDP to survive past a day.
* ``c0ab8ce9`` is the Office web Copilot *native* public client -- the same appid
  our CDP-captured substrate tokens already carry. Its RT is a normal sliding
  refresh token, so one interactive PKCE login can be kept alive by HTTP alone.
  Native redemption must NOT carry an Origin header, or AAD treats it as an SPA
  request.

Media and designer tokens are the same client with a different audience, so
``mint_scoped_token`` produces them from the same RT -- no browser needed.
"""
from __future__ import annotations

import re
import time

from .account_store import AccountStore
from .token_store import decode_jwt_payload, is_substrate_token_claims
from .runtime_flags import elog, ulog

# The Copilot SPA's public client id (same one seen in our capture logs and in
# the MSAL refresh-token cache key). Public client => no secret needed.
M365_REFRESH_CLIENT_ID = "4765445b-32c6-49b0-83e6-1d93765276ca"
# The Office web Copilot native public client. Measured 2026-08-17: this is the
# appid on the substrate/media tokens our own CDP capture already yields, and it
# is the client the interactive PKCE login uses.
M365_NATIVE_CLIENT_ID = "c0ab8ce9-e9a0-42e7-b064-33d422df41f1"
M365_REFRESH_CLIENT_IDS = frozenset({M365_REFRESH_CLIENT_ID, M365_NATIVE_CLIENT_ID})
# Match the browser/MSAL flow. offline_access is what permits a rotated RT in
# the response; openid/profile keep the request aligned with the issuing flow.
M365_REFRESH_SCOPE = (
    "https://substrate.office.com/sydney/.default openid profile offline_access"
)
# Media/designer audiences, read off real captured tokens: the Teams media token
# is aud=ic3.teams.office.com, and Designer image downloads want a
# designerappservice token (returned as an opaque JWE, not a JWT).
M365_MEDIA_SCOPE = "https://ic3.teams.office.com/.default"
M365_DESIGNER_SCOPE = "https://designerappservice.officeapps.live.com/.default"
_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
# Origin header mirrors the SPA so AAD treats the request like the real client.
# Native clients must not send it (see module docstring).
_ORIGIN = "https://m365.cloud.microsoft"
_HTTP_TIMEOUT_SECONDS = 20
_RETRYABLE_ERROR_BACKOFF_SECONDS = 15 * 60
_TERMINAL_AADSTS_CODES = {"50173", "70008", "70043", "700082", "700084"}
_GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_AUTHORITY_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,126}[a-z0-9])?$", re.IGNORECASE)


def normalize_microsoft_id(value: object) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if _GUID_RE.fullmatch(candidate) else ""


def normalize_m365_authority(value: object) -> str:
    candidate = str(value or "").strip().lower()
    if candidate == "consumers" or not _AUTHORITY_RE.fullmatch(candidate):
        return ""
    return candidate


def account_matches_refresh_subject(account, tenant_id: str, object_id: str) -> bool:
    try:
        claims = decode_jwt_payload(getattr(account, "token", "") or "")
    except Exception:
        return False
    return (
        normalize_microsoft_id(claims.get("tid")) == tenant_id
        and normalize_microsoft_id(claims.get("oid")) == object_id
    )


def _stored_binding(account) -> tuple[str, str, str, str] | None:
    client_id = str(getattr(account, "refresh_token_client_id", "") or "").lower()
    authority = normalize_m365_authority(
        getattr(account, "refresh_token_authority", "")
    )
    tenant_id = normalize_microsoft_id(
        getattr(account, "refresh_token_tenant_id", "")
    )
    object_id = normalize_microsoft_id(
        getattr(account, "refresh_token_object_id", "")
    )
    if (
        client_id not in M365_REFRESH_CLIENT_IDS
        or not authority
        or not tenant_id
        or not object_id
        or not account_matches_refresh_subject(account, tenant_id, object_id)
    ):
        return None
    return client_id, authority, tenant_id, object_id


def _token_request_headers(client_id: str) -> dict[str, str]:
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if client_id == M365_REFRESH_CLIENT_ID:
        headers["Origin"] = _ORIGIN
    return headers


async def _post_token(
    *, authority: str, client_id: str, refresh_token: str, scope: str
):
    import httpx

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        return await client.post(
            _TOKEN_URL.format(tenant=authority),
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": scope,
            },
            headers=_token_request_headers(client_id),
        )


async def mint_scoped_token(
    accounts: AccountStore, account_id: str, scope: str
) -> tuple[str, str]:
    """Redeem the stored RT for a token on another audience (media/designer).

    Returns ``(access_token, error)``; exactly one is non-empty. The token is
    returned rather than stored because each audience has its own setter, and it
    is deliberately NOT validated as a JWT: Designer hands back an opaque JWE.
    A rotated RT is persisted here, since dropping it would strand the chain.
    """
    account = accounts.get(account_id)
    if account is None:
        return "", "unknown account"
    rt = (getattr(account, "refresh_token", "") or "").strip()
    if not rt:
        return "", "no stored refresh_token"
    binding = _stored_binding(account)
    if binding is None:
        return "", "stored RT has no verified client/authority/subject binding"
    client_id, authority, _tenant_id, _object_id = binding
    try:
        resp = await _post_token(
            authority=authority,
            client_id=client_id,
            refresh_token=rt,
            # offline_access keeps the chain alive: without it AAD returns no
            # rotated RT and this audience hop would consume the grant silently.
            scope=f"{scope} offline_access",
        )
    except Exception as exc:  # noqa: BLE001 - network failure is just a miss
        return "", f"HTTP error: {exc}"
    if resp.status_code != 200:
        _oauth_error, _codes, detail = _error_info(resp)
        return "", f"HTTP {resp.status_code} {detail}".strip()
    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        return "", f"cannot parse token response: {exc}"
    access_token = str(payload.get("access_token", "") or "")
    if not access_token:
        return "", "no access_token in response"
    rotated = payload.get("refresh_token")
    if isinstance(rotated, str) and rotated and rotated != rt:
        # None binding args preserve the verified client/authority/subject.
        accounts.set_refresh_token(account_id, rotated, expected_refresh_token=rt)
    return access_token, ""


async def refresh_via_rt(accounts: AccountStore, account_id: str) -> bool:
    """Exchange the account's stored refresh_token for a fresh substrate token.

    Returns True and persists the new access token (+ rotated refresh_token) on
    success. Returns False (leaving existing state intact) when the account has
    no refresh_token, the exchange fails, the response is not a substrate token,
    or the captured identity conflicts with the account's known email.
    """
    account = accounts.get(account_id)
    if account is None:
        return False
    rt = (getattr(account, "refresh_token", "") or "").strip()
    if not rt:
        return False
    binding = _stored_binding(account)
    if binding is None:
        accounts.set_refresh_token(
            account_id, "", expected_refresh_token=rt
        )
        elog(
            f"RT refresh skipped for {account_id}: stored RT has no verified "
            "client/authority/subject binding; discarded, falling back to CDP"
        )
        return False

    client_id, authority, tenant_id, object_id = binding
    expected_access_token = account.token

    try:
        resp = await _post_token(
            authority=authority,
            client_id=client_id,
            refresh_token=rt,
            scope=M365_REFRESH_SCOPE,
        )
    except Exception as exc:
        _defer_rt(accounts, account_id, rt)
        elog(
            f"RT refresh failed for {account_id}: HTTP error: {exc}; RT kept but "
            f"paused for {_RETRYABLE_ERROR_BACKOFF_SECONDS // 60}m, falling back to CDP"
        )
        return False

    if resp.status_code != 200:
        oauth_error, aadsts_codes, detail = _error_info(resp)
        if oauth_error == "invalid_grant" and aadsts_codes & _TERMINAL_AADSTS_CODES:
            accounts.set_refresh_token(
                account_id, "", expected_refresh_token=rt
            )
            suffix = "stored RT expired/revoked and was disabled"
        else:
            _defer_rt(accounts, account_id, rt)
            suffix = (
                f"RT kept but paused for {_RETRYABLE_ERROR_BACKOFF_SECONDS // 60}m"
            )
        elog(
            f"RT refresh failed for {account_id}: HTTP {resp.status_code} "
            f"{detail}; {suffix}, falling back to CDP"
        )
        return False

    try:
        payload = resp.json()
    except Exception as exc:
        _defer_rt(accounts, account_id, rt)
        elog(f"RT refresh failed for {account_id}: cannot parse token response: {exc}")
        return False

    access_token = payload.get("access_token")
    if not access_token:
        _defer_rt(accounts, account_id, rt)
        elog(f"RT refresh failed for {account_id}: no access_token in response")
        return False

    # Validate it really is a substrate token before trusting it.
    try:
        claims = decode_jwt_payload(access_token)
    except Exception as exc:
        _defer_rt(accounts, account_id, rt)
        elog(f"RT refresh failed for {account_id}: access_token not a JWT: {exc}")
        return False
    if not is_substrate_token_claims(claims):
        _defer_rt(accounts, account_id, rt)
        elog(f"RT refresh failed for {account_id}: token aud={claims.get('aud')!r} is not substrate")
        return False

    captured_tenant = normalize_microsoft_id(claims.get("tid"))
    captured_object = normalize_microsoft_id(claims.get("oid"))
    if captured_tenant != tenant_id or captured_object != object_id:
        accounts.set_refresh_token(
            account_id, "", expected_refresh_token=rt
        )
        elog(
            f"RT refresh rejected for {account_id}: subject mismatch "
            f"(expected oid/tid={object_id}/{tenant_id}, "
            f"captured={captured_object}/{captured_tenant}); stored RT disabled"
        )
        return False

    rotated = payload.get("refresh_token")
    stored = accounts.apply_refresh_token_result(
        account_id,
        expected_refresh_token=rt,
        expected_access_token=expected_access_token,
        access_token=access_token,
        rotated_refresh_token=rotated if isinstance(rotated, str) else "",
    )
    if stored is None:
        ulog(
            f"RT refresh response discarded for {account_id}: newer credentials "
            "were pushed while the HTTP exchange was in flight"
        )
        return False
    seconds = max(0, int(claims.get("exp", 0)) - int(time.time()))
    ulog(
        f"RT refresh succeeded for {account_id}: substrate token via HTTP "
        f"(expires in {seconds}s, rotated_rt={'yes' if rotated and rotated != rt else 'no'})"
    )
    return True


def _defer_rt(accounts: AccountStore, account_id: str, rt: str) -> None:
    accounts.defer_refresh_token(
        account_id,
        rt,
        time.time() + _RETRYABLE_ERROR_BACKOFF_SECONDS,
    )


def _error_info(resp) -> tuple[str, set[str], str]:
    """Return OAuth error, numeric AADSTS codes, and a compact safe summary."""
    try:
        body = resp.json()
        oauth_error = str(body.get("error", "") or "")
        desc = str(body.get("error_description", ""))
        first = desc.splitlines()[0] if desc else ""
        aadsts_codes = {
            str(code)
            for code in body.get("error_codes", [])
            if str(code).isdigit()
        } if isinstance(body.get("error_codes"), list) else set()
        match = re.search(r"AADSTS(\d+)", desc, re.IGNORECASE)
        if match:
            aadsts_codes.add(match.group(1))
        return oauth_error, aadsts_codes, f"{oauth_error}: {first}".strip(": ")
    except Exception:
        return "", set(), ""
