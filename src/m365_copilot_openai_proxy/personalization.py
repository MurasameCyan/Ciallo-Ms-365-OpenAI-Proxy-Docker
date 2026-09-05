"""Read and write the account-level personalization flags M365 keeps.

M365's "memory" hangs off the **account**, not off a conversation, so something
it stored during an earlier session is an input to every later turn -- including
turns this bridge serves for a user who never saw that session. Nothing here used
to read it, which made it the one input an operator could not inspect while
debugging "same prompt, different answer".

Measured against the live account on 2026-09-05 (`.probe/personalization_*.py`),
two rules shape this module:

  1. **The POST echoes no flags.** It answers 200 with `result.value == "Success"`
     and a message, nothing else -- so a read-back is the only proof a write
     landed, and it is the read-back that callers are handed.
  2. **A partial POST has coupling.** Sending `{"isMemoryEnabled": false}` alone
     also turned `isInsightsFromConversationHistoryEnabled` off. So a write goes
     out with all four flags merged over a fresh read, and the caller is told the
     whole re-read state rather than "the one flag you asked for".

The endpoint, the header set and the flag names are protocol facts taken from
KilimcininKorOglu/M365Bridge's v1.5.0 notes. That repo carries no LICENSE, so
nothing is copied from it -- the calls here were written and then measured
independently.
"""

from __future__ import annotations

import uuid

import httpx

from .account_store import AccountStore
from .token_store import decode_jwt_payload

_ENDPOINT = (
    "https://substrate.office.com/m365Copilot/PersonalizationUserFlags"
    "?variants=feature.EnablePersonalization"
)
_ORIGIN = "https://m365.cloud.microsoft"
_HTTP_TIMEOUT_SECONDS = 20

# The four the operator can move. Order is the order the /admin panel lists them:
# memory first because it is the one that changes what a turn sees.
PERSONALIZATION_FLAGS = (
    "isMemoryEnabled",
    "isInsightsFromConversationHistoryEnabled",
    "isCustomInstructionEnabled",
    "isM365GraphContentEnabled",
)
# Read-only: the tenant's own switch. When it is off, the four above cannot be
# written -- which has to be said out loud, because the endpoint still answers
# "Success" for a write that changes nothing.
TENANT_FLAG = "isPersonalizationEnabledByTenant"


class PersonalizationError(RuntimeError):
    """One account's personalization settings could not be read or written.

    The message is shown verbatim in /admin, so it is written in Chinese for the
    operator rather than in English for the log; interpolated technical detail
    (HTTP status, upstream exception) stays as-is. ``status`` is the HTTP code the
    admin route answers with, so a new failure kind never needs a route change.
    """

    status = 502


class PersonalizationUnavailable(PersonalizationError):
    """This account cannot have personalization settings at all (not a failure)."""

    status = 400


class TenantForbidsPersonalization(PersonalizationError):
    """The tenant switch is off, so the four flags are not writable."""

    status = 409


def _identity(accounts: AccountStore, account_id: str) -> tuple[str, str, str]:
    """(substrate token, oid, tid) for one account, or a reason it has none."""
    account = accounts.get(account_id)
    if account is None:
        raise PersonalizationError("账户不存在")
    if getattr(account, "provider", "m365") != "m365":
        raise PersonalizationUnavailable(
            "个性化设置只有 M365 账户有（该账户是个人版 Copilot）"
        )
    token = (getattr(account, "token", "") or "").strip()
    if not token:
        raise PersonalizationUnavailable("该账户没有可用的 substrate 令牌，请先刷新账户")
    try:
        claims = decode_jwt_payload(token)
    except Exception as exc:  # noqa: BLE001 - an opaque token is just "unusable"
        raise PersonalizationUnavailable(f"该账户的令牌无法解析：{exc}") from exc
    oid = str((claims or {}).get("oid") or "").strip()
    tid = str((claims or {}).get("tid") or "").strip()
    if not oid or not tid:
        # X-AnchorMailbox is what routes the request to this mailbox; without it
        # the endpoint has no subject to answer for.
        raise PersonalizationUnavailable(
            "该账户的令牌里没有 oid/tid，无法定位邮箱，请重新登录该账户"
        )
    return token, oid, tid


def _headers(token: str, oid: str, tid: str) -> dict[str, str]:
    return {
        "accept": "*/*",
        "accept-language": "en-us",
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "origin": _ORIGIN,
        "referer": f"{_ORIGIN}/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "x-anchormailbox": f"Oid:{oid}@{tid}",
        "x-clientrequestid": str(uuid.uuid4()),
        "x-routingparameter-sessionkey": oid,
        "x-scenario": "OfficeWebIncludedCopilot",
    }


def _parse(raw: object, action: str) -> dict:
    """The five flags as a state dict, or a protocol complaint.

    A flag missing from the body is NOT read as False: that False would be posted
    back on the next write and silently turn a setting off.
    """
    if not isinstance(raw, dict):
        raise PersonalizationError(f"{action}返回的响应结构不符合预期")
    for flag in (*PERSONALIZATION_FLAGS, TENANT_FLAG):
        if flag not in raw:
            raise PersonalizationError(
                f"{action}的响应里缺少 {flag}（上游协议变了？）"
            )
    return {
        "flags": {flag: bool(raw[flag]) for flag in PERSONALIZATION_FLAGS},
        "tenant_allowed": bool(raw[TENANT_FLAG]),
    }


async def _call(
    token: str,
    oid: str,
    tid: str,
    action: str,
    body: dict | None = None,
) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            headers = _headers(token, oid, tid)
            if body is None:
                resp = await client.get(_ENDPOINT, headers=headers)
            else:
                resp = await client.post(_ENDPOINT, headers=headers, json=body)
    except Exception as exc:  # noqa: BLE001 - any transport error is "unavailable"
        raise PersonalizationError(f"{action}失败：{exc}") from exc
    if resp.status_code in (401, 403):
        raise PersonalizationError(
            f"{action}失败：HTTP {resp.status_code}（令牌可能已过期，请先刷新账户）"
        )
    if resp.status_code < 200 or resp.status_code >= 300:
        raise PersonalizationError(f"{action}失败：HTTP {resp.status_code}")
    return resp


async def _get_state(token: str, oid: str, tid: str, action: str) -> dict:
    resp = await _call(token, oid, tid, action)
    try:
        parsed = resp.json()
    except Exception as exc:  # noqa: BLE001 - Cloudflare/login HTML lands here
        raise PersonalizationError(f"{action}返回了非 JSON 响应") from exc
    return _parse(parsed, action)


async def read_flags(accounts: AccountStore, account_id: str) -> dict:
    """``{"flags": {four bools}, "tenant_allowed": bool}`` for one account."""
    token, oid, tid = _identity(accounts, account_id)
    return await _get_state(token, oid, tid, "读取个性化设置")


async def write_flags(accounts: AccountStore, account_id: str, changes: dict) -> dict:
    """Apply ``changes`` and answer with what the account reads back afterwards.

    ``changes`` names only the flags the operator moved; everything else is sent
    at its current value because a partial body moves flags nobody asked about
    (rule 2 in the module docstring). The returned state comes from a fresh read,
    never from ``changes`` -- the POST body is a request, not a result.
    """
    if not isinstance(changes, dict) or not changes:
        raise ValueError("没有要修改的个性化开关")
    for flag, value in changes.items():
        if flag not in PERSONALIZATION_FLAGS:
            raise ValueError(f"未知的个性化开关：{flag}")
        if not isinstance(value, bool):
            raise ValueError(f"个性化开关 {flag} 只接受 true/false")

    token, oid, tid = _identity(accounts, account_id)
    current = await _get_state(token, oid, tid, "读取个性化设置")
    if not current["tenant_allowed"]:
        raise TenantForbidsPersonalization(
            "该租户禁用了个性化设置，这四个开关改不动（需要租户管理员放开）"
        )
    body = {flag: bool(changes.get(flag, current["flags"][flag])) for flag in PERSONALIZATION_FLAGS}
    await _call(token, oid, tid, "保存个性化设置", body)
    # The POST echoed no flags, so this read is the only evidence of what happened.
    return await _get_state(token, oid, tid, "回读个性化设置")
