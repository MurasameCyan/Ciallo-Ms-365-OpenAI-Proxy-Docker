"""HTTP MSA refresh_token -> consumer ChatAI token exchange (no browser).

WHY THIS EXISTS. The consumer (personal-account) path renewed its credential by
launching Camoufox and letting in-page MSAL mint a fresh ChatAI token from the
MSA session cookies. That works, but it costs a ~936 MB browser dependency, a
~7s cold launch, and the single-browser lock every other refresh path queues on.

Measured on the deployed container against the live account (2026-09-16): the RT
that MSAL already caches redeems over plain HTTP in ~1.4s, with no browser, no
cookies on the request, and the resulting ChatAI token carried a real chat turn
on all three protocols. So this is the fast path, and Camoufox becomes the
fallback for when there is no usable RT.

DELIBERATELY SEPARATE FROM refresh_via_rt. That module redeems an AAD grant for
the substrate audience and binds it to a tenant/object subject. An MSA grant has
neither: it is bound to its issuing client and the scope it was minted for, and
the identity lives in `client_info` rather than a tenant/oid pair. Sharing one
module (or one stored field) would let an M365 code path redeem a consumer grant
against a binding it never verified.

WHAT IS AND IS NOT VERIFIED. The client_id and scope are replayed verbatim from
what was captured, never hardcoded defaults, so a Microsoft-side rollout cannot
silently strand a credential. The identity that comes back is checked against the
account's pinned Microsoft subject before anything is written, because an RT for
another personal account would otherwise overwrite working credentials with
someone else's session.

Token values are never logged -- only lengths, presence, and AADSTS codes.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import time

from .account_store import AccountStore, _normalize_consumer_account_id
from .runtime_flags import elog, ulog

# MSA-only authority. `consumers` is what the personal-account tenant resolves
# to (verified against the published OIDC metadata: it issues for tenant
# 9188040d-6c67-4c5b-b112-36a304b66dad, the MSA tenant), and pinning it here
# keeps a consumer grant from being replayed against an organisational tenant.
CONSUMER_AUTHORITY = "consumers"
_TOKEN_URL = f"https://login.microsoftonline.com/{CONSUMER_AUTHORITY}/oauth2/v2.0/token"
# The Copilot consumer SPA's public client id and the ChatAI scope, as measured
# in the live MSAL cache. Used only to sanity-check a push and as the seed for a
# credential captured before these fields existed -- the stored values always win.
CONSUMER_CLIENT_ID = "14638111-3389-403d-b206-a6a71d9f8f16"
CONSUMER_CHATAI_SCOPE = "140e65af-45d1-4427-bf08-3e7295db6836/ChatAI.ReadWrite"
# Origin mirrors the page that owns the MSAL cache, matching what the browser's
# own silent renewal sends.
_ORIGIN = "https://copilot.microsoft.com"
_HTTP_TIMEOUT_SECONDS = 20
_RETRYABLE_ERROR_BACKOFF_SECONDS = 15 * 60
# invalid_grant carrying one of these means the grant itself is gone, so retrying
# only burns a round trip per keepalive tick. Anything else is treated as a blip
# and backed off instead of discarded.
_TERMINAL_AADSTS_CODES = {"50173", "50076", "70008", "70043", "700082", "700084", "9002313"}
_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# An MSAL scope entry is `<resource-guid>/<Scope.Name>` or a full URI. Kept loose
# on purpose (Microsoft owns this format) but bounded, because the value is
# replayed into an outbound request body.
_SCOPE_RE = re.compile(r"^[A-Za-z0-9;:/._~%-]{1,400}$")
# Bounds for the opaque credential itself. The live RT measured 521 chars; the
# ceiling only exists so a malformed push cannot store an unbounded blob.
_MIN_RT_LENGTH = 40
_MAX_RT_LENGTH = 8192


def normalize_consumer_client_id(value: object) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if _GUID_RE.fullmatch(candidate) else ""


def normalize_consumer_scope(value: object) -> str:
    """One scope entry, with `offline_access`/`openid`/`profile` stripped.

    Those three are added at redemption time. Accepting them here would let a
    push store a scope string that redeems for a different audience than the
    ChatAI token the account actually needs.
    """
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    # Split FIRST, then validate the surviving entry: the pattern below has no
    # whitespace in it, so matching the raw string would reject every
    # multi-part scope -- which is the form both the MSAL cache and a token
    # response actually carry -- and make the stripping here unreachable.
    parts = [
        part
        for part in candidate.split()
        if part.lower() not in {"offline_access", "openid", "profile", "email"}
    ]
    if len(parts) != 1 or not _SCOPE_RE.fullmatch(parts[0]):
        return ""
    return parts[0]


def normalize_consumer_refresh_token(value: object) -> str:
    """The RT string, or "" when it is not plausibly one.

    Opaque, so only shape is checkable: no whitespace (it travels in a form body)
    and within measured bounds.
    """
    candidate = str(value or "").strip()
    if not _MIN_RT_LENGTH <= len(candidate) <= _MAX_RT_LENGTH:
        return ""
    return "" if any(char.isspace() for char in candidate) else candidate


def account_id_from_client_info(client_info: object) -> str:
    """The pinned-subject form (`home:<uid>.<utid>`) of a token response's identity.

    MSAL builds its homeAccountId from exactly these two fields, so this is the
    same string the browser gate reports -- which is what makes the two paths
    comparable against one stored subject.
    """
    raw = str(client_info or "").strip()
    if not raw:
        return ""
    # base64url without padding, as AAD sends it.
    padded = raw + "=" * (-len(raw) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, binascii.Error, UnicodeEncodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    uid = str(payload.get("uid", "") or "").strip().lower()
    utid = str(payload.get("utid", "") or "").strip().lower()
    if not uid or not utid:
        return ""
    return _normalize_consumer_account_id(f"home:{uid}.{utid}")


def stored_consumer_binding(account) -> tuple[str, str] | None:
    """(client_id, scope) for a redeemable stored RT, else None.

    None means "do not attempt": a non-empty RT with no verified binding cannot
    be replayed correctly, and guessing the client/scope would either fail or --
    worse -- succeed against an audience nobody asked for.
    """
    if account is None or getattr(account, "provider", "m365") != "consumer":
        return None
    if not normalize_consumer_refresh_token(getattr(account, "consumer_refresh_token", "")):
        return None
    client_id = normalize_consumer_client_id(
        getattr(account, "consumer_refresh_token_client_id", "")
    )
    scope = normalize_consumer_scope(
        getattr(account, "consumer_refresh_token_scope", "")
    )
    if not client_id or not scope:
        return None
    return client_id, scope


def _error_info(resp) -> tuple[str, set[str], str]:
    """OAuth error, numeric AADSTS codes, and a compact safe summary."""
    try:
        body = resp.json()
        oauth_error = str(body.get("error", "") or "")
        desc = str(body.get("error_description", "") or "")
        first = desc.splitlines()[0] if desc else ""
        raw_codes = body.get("error_codes")
        codes = {
            str(code)
            for code in (raw_codes if isinstance(raw_codes, list) else [])
            if str(code).isdigit()
        }
        match = re.search(r"AADSTS(\d+)", desc, re.IGNORECASE)
        if match:
            codes.add(match.group(1))
        return oauth_error, codes, f"{oauth_error}: {first}".strip(": ")
    except Exception:  # noqa: BLE001 - a body we cannot parse is still a failure
        return "", set(), ""


def _disabled_reason(aadsts_codes: set[str]) -> str:
    """A stable code naming why the RT is being discarded.

    Stable codes rather than prose for the same reason as the M365 path: the
    value is persisted and rendered in two languages.
    """
    if "700084" in aadsts_codes:
        return "consumer_rt_lifetime"
    if aadsts_codes & {"50173", "50076"}:
        return "consumer_reauth_required"
    return "consumer_rt_revoked"


async def _post_token(*, client_id: str, refresh_token: str, scope: str, proxy: str):
    import httpx

    # The credential is scored against the IP that earned it, so the exchange
    # must leave through the same egress the chat turns use.
    kwargs = {"timeout": _HTTP_TIMEOUT_SECONDS}
    if proxy:
        kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**kwargs) as client:
        return await client.post(
            _TOKEN_URL,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                # MSA omits the subject metadata unless explicitly requested.
                # The pinned-account check below requires MSAL's uid/utid pair.
                "client_info": "1",
                # offline_access keeps the chain alive: without it AAD returns no
                # rotated RT and this renewal would consume the grant silently.
                "scope": f"{scope} openid profile offline_access",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": _ORIGIN,
            },
        )


async def refresh_consumer_via_rt(accounts: AccountStore, account_id: str) -> bool:
    """Renew one consumer account's ChatAI token from its stored MSA RT.

    Returns True only when a fresh token was persisted. False leaves every
    stored credential untouched, so the caller can fall back to the browser gate
    -- a failure here is a missed shortcut, not a dead account.
    """
    account = accounts.get(account_id)
    if account is None or getattr(account, "provider", "m365") != "consumer":
        return False

    rt = normalize_consumer_refresh_token(getattr(account, "consumer_refresh_token", ""))
    if not rt:
        return False

    retry_after = float(getattr(account, "consumer_refresh_token_retry_after", 0.0) or 0.0)
    if retry_after > time.time():
        return False

    binding = stored_consumer_binding(account)
    if binding is None:
        # A stored RT we cannot replay is worse than none: it makes the UI claim
        # a fast path exists while every attempt is skipped.
        accounts.set_consumer_refresh_token(
            account_id, "", expected_refresh_token=rt, disabled_reason="consumer_rt_unbound"
        )
        elog(
            f"Consumer RT refresh skipped for {account_id}: stored RT has no verified "
            "client/scope binding; discarded, falling back to the browser gate"
        )
        return False

    client_id, scope = binding
    expected_subject = _normalize_consumer_account_id(
        getattr(account, "consumer_account_id", "")
    )
    if not expected_subject:
        elog(
            f"Consumer RT refresh skipped for {account_id}: no pinned Microsoft "
            "account id to verify the exchange against"
        )
        return False
    expected_consumer_token = str(getattr(account, "consumer_token", "") or "")
    proxy = str(getattr(account, "proxy_url", "") or "")

    try:
        resp = await _post_token(
            client_id=client_id, refresh_token=rt, scope=scope, proxy=proxy
        )
    except Exception as exc:  # noqa: BLE001 - a network failure is just a miss
        accounts.defer_consumer_refresh_token(
            account_id, rt, time.time() + _RETRYABLE_ERROR_BACKOFF_SECONDS
        )
        elog(
            f"Consumer RT refresh failed for {account_id}: HTTP error: {exc}; RT kept "
            f"but paused for {_RETRYABLE_ERROR_BACKOFF_SECONDS // 60}m"
        )
        return False

    if resp.status_code != 200:
        oauth_error, codes, detail = _error_info(resp)
        if oauth_error == "invalid_grant" and codes & _TERMINAL_AADSTS_CODES:
            accounts.set_consumer_refresh_token(
                account_id,
                "",
                expected_refresh_token=rt,
                disabled_reason=_disabled_reason(codes),
            )
            suffix = "stored RT expired/revoked and was disabled"
        else:
            accounts.defer_consumer_refresh_token(
                account_id, rt, time.time() + _RETRYABLE_ERROR_BACKOFF_SECONDS
            )
            suffix = f"RT kept but paused for {_RETRYABLE_ERROR_BACKOFF_SECONDS // 60}m"
        elog(
            f"Consumer RT refresh failed for {account_id}: HTTP {resp.status_code} "
            f"{detail}; {suffix}, falling back to the browser gate"
        )
        return False

    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        elog(f"Consumer RT refresh for {account_id}: cannot parse response: {exc}")
        return False
    if not isinstance(payload, dict):
        elog(f"Consumer RT refresh for {account_id}: response was not an object")
        return False

    fresh_token = str(payload.get("access_token", "") or "").strip()
    if not fresh_token:
        elog(f"Consumer RT refresh for {account_id}: no access_token in response")
        return False

    actual_subject = account_id_from_client_info(payload.get("client_info"))
    if actual_subject != expected_subject:
        # Never a retry: the grant belongs to a different personal account, so
        # replaying it can only ever overwrite this account with someone else's
        # session. Discard rather than back off.
        accounts.set_consumer_refresh_token(
            account_id,
            "",
            expected_refresh_token=rt,
            disabled_reason="consumer_rt_subject_mismatch",
        )
        elog(
            f"Consumer RT refresh rejected for {account_id}: the exchange returned a "
            "different Microsoft account; RT discarded"
        )
        return False

    rotated = str(payload.get("refresh_token", "") or "").strip()
    try:
        expires_in = int(payload.get("expires_in", 0) or 0)
    except (TypeError, ValueError):
        expires_in = 0
    expires_at = time.time() + expires_in if expires_in > 0 else 0.0

    stored = accounts.apply_consumer_refresh_result(
        account_id,
        expected_refresh_token=rt,
        expected_consumer_token=expected_consumer_token,
        consumer_token=fresh_token,
        rotated_refresh_token=rotated,
        expires_at=expires_at,
    )
    if stored is None:
        elog(
            f"Consumer RT refresh discarded for {account_id}: credentials changed "
            "while the exchange was in flight"
        )
        return False

    ulog(
        f"Consumer RT refresh for {account_id}: minted a ChatAI token "
        f"({len(fresh_token)} chars, expires_in={expires_in}s) without a browser"
    )
    return True
