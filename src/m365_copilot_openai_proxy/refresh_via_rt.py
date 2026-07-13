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
    scope         = https://substrate.office.com/sydney/.default

The response carries an access_token (aud=https://substrate.office.com/) and a
rotated refresh_token, which we persist so the chain keeps renewing. media and
designer tokens are a different client/flow and are NOT produced here; they are
kept alive lazily by the CDP media capture path.
"""
from __future__ import annotations

import time

from .account_store import AccountStore, extract_identity
from .token_store import decode_jwt_payload, is_substrate_token_claims

# The Copilot SPA's public client id (same one seen in our capture logs and in
# the MSAL refreshtoken cache key). Public client => no secret needed.
_CLIENT_ID = "4765445b-32c6-49b0-83e6-1d93765276ca"
# Scope MUST include /sydney/ -- a bare substrate.office.com/.default is a
# different resource and is rejected for this client.
_SCOPE = "https://substrate.office.com/sydney/.default"
_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
# Origin header mirrors the SPA so AAD treats the request like the real client.
_ORIGIN = "https://m365.cloud.microsoft"
_HTTP_TIMEOUT_SECONDS = 20


def _tenant_for_account(account) -> str:
    """Best-effort tenant id for the token endpoint.

    The refresh_token itself encodes the tenant, so the multi-tenant
    `organizations` authority works as a fallback, but using the account's own
    tenant id (from the current substrate token's `tid` claim) is more precise
    and avoids surprises with guest/multi-tenant identities.
    """
    token = getattr(account, "token", "") or ""
    if token:
        try:
            claims = decode_jwt_payload(token)
            tid = claims.get("tid")
            if isinstance(tid, str) and tid:
                return tid
        except Exception:
            pass
    return "organizations"


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

    tenant = _tenant_for_account(account)
    data = {
        "client_id": _CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "scope": _SCOPE,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": _ORIGIN,
    }

    import httpx

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(_TOKEN_URL.format(tenant=tenant), data=data, headers=headers)
    except Exception as exc:
        print(f"RT refresh failed for {account_id}: HTTP error: {exc}", flush=True)
        return False

    if resp.status_code != 200:
        # AADSTS codes here (e.g. invalid_grant when the RT chain is dead) tell
        # us the RT is no longer usable, so the caller falls back to CDP.
        detail = _error_detail(resp)
        print(f"RT refresh failed for {account_id}: HTTP {resp.status_code} {detail}", flush=True)
        return False

    try:
        payload = resp.json()
    except Exception as exc:
        print(f"RT refresh failed for {account_id}: cannot parse token response: {exc}", flush=True)
        return False

    access_token = payload.get("access_token")
    if not access_token:
        print(f"RT refresh failed for {account_id}: no access_token in response", flush=True)
        return False

    # Validate it really is a substrate token before trusting it.
    try:
        claims = decode_jwt_payload(access_token)
    except Exception as exc:
        print(f"RT refresh failed for {account_id}: access_token not a JWT: {exc}", flush=True)
        return False
    if not is_substrate_token_claims(claims):
        print(f"RT refresh failed for {account_id}: token aud={claims.get('aud')!r} is not substrate", flush=True)
        return False

    # Identity guard: never overwrite an established account with a token that
    # decodes to a different identity (mirrors the CDP path's guard).
    if account.email:
        _, captured_email = extract_identity(access_token)
        if captured_email and captured_email.lower() != account.email.lower():
            print(
                f"RT refresh rejected for {account_id}: identity mismatch "
                f"(account={account.email!r}, captured={captured_email!r})",
                flush=True,
            )
            return False

    # Persist the rotated refresh_token FIRST so a crash right after can't lose
    # the new RT while the old one is already invalidated by AAD.
    rotated = payload.get("refresh_token")
    if isinstance(rotated, str) and rotated and rotated != rt:
        accounts.set_refresh_token(account_id, rotated)

    # Preserve the existing token_source (None = leave unchanged): an RT refresh
    # neither creates nor removes a signed-in Chromium profile, so a "manual"
    # account stays "manual" and a "cdp" account stays "cdp".
    accounts.update_token(account_id, access_token)
    seconds = max(0, int(claims.get("exp", 0)) - int(time.time()))
    print(
        f"RT refresh succeeded for {account_id}: substrate token via HTTP "
        f"(expires in {seconds}s, rotated_rt={'yes' if rotated and rotated != rt else 'no'})",
        flush=True,
    )
    return True


def _error_detail(resp) -> str:
    """Compact AADSTS error summary for logs (no token material)."""
    try:
        body = resp.json()
        code = body.get("error", "")
        desc = str(body.get("error_description", ""))
        # First line of the description carries the AADSTS code + summary.
        first = desc.splitlines()[0] if desc else ""
        return f"{code}: {first}".strip(": ")
    except Exception:
        return ""
