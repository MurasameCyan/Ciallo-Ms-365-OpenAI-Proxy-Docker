"""M365 cloud conversation management (list / delete / cleanup) per pool account.

The chat WebSocket (``substrate_client``) can create and continue conversations
but cannot enumerate or delete them. The m365.cloud.microsoft SPA does that
through an action API -- ``POST /chat`` with ``{"action": ..., "state": ...}`` --
which wants an access token for the SPA's own audience
(``https://m365.cloud.microsoft/v2/``), not the substrate token each account
stores. So the token is minted on demand from that account's own refresh token,
through the same client/authority/subject binding checks the substrate refresh
path applies, and cached in memory only: it must never be written over
``account.token``, which has to stay the substrate one.

Everything here is per account. An account with no verified refresh-token
binding simply has no cloud management (the caller surfaces that as a warning and
still shows the local sessions), rather than borrowing another account's client.

Protocol reference: HEXUXIU/M365-Copilot2API (MIT), internal/web/m365cloud.go.
"""
from __future__ import annotations

import json
import threading
import time

from .account_store import AccountStore
from .refresh_via_rt import (
    _post_token,
    _stored_binding,
    normalize_microsoft_id,
)
from .runtime_flags import elog
from .token_store import decode_jwt_payload

# No offline_access on purpose: this exchange must not rotate the refresh token
# that the substrate refresh path owns and persists.
_CLOUD_SCOPE = "https://m365.cloud.microsoft/v2/.default"
_CHAT_URL = "https://m365.cloud.microsoft/chat"
_ORIGIN = "https://m365.cloud.microsoft"
_HTTP_TIMEOUT_SECONDS = 20
# Microsoft's history list is a sliding window: RefreshNavPane returns one screen
# of conversations, and older ones move up as rows are deleted. So cleanup
# re-lists until a round deletes nothing, bounded so a server-side quirk can
# never spin forever.
_CLEANUP_MAX_ROUNDS = 100
_TOKEN_EXPIRY_SKEW_SECONDS = 120

# ponytail: process-local token cache (account_id -> (token, expires_at)). Keeps
# an admin "all users" page load from minting one token per account on every
# refresh. Single-process uvicorn, so no cross-worker sharing is needed; if this
# ever runs multi-worker the only cost is one extra mint per worker.
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_CACHE_LOCK = threading.Lock()
# Hit/miss counters for the admin cache panel. A miss is one full token exchange
# against login.microsoftonline.com, so the ratio is what says whether the cache
# is doing its job on an "all users" page load.
_TOKEN_CACHE_HITS = 0
_TOKEN_CACHE_MISSES = 0


class CloudSessionError(RuntimeError):
    """Cloud conversation management is unavailable or failed for one account."""


def token_cache_stats() -> dict:
    with _TOKEN_CACHE_LOCK:
        looked_up = _TOKEN_CACHE_HITS + _TOKEN_CACHE_MISSES
        return {
            "entries": len(_TOKEN_CACHE),
            "hits": _TOKEN_CACHE_HITS,
            "misses": _TOKEN_CACHE_MISSES,
            "hit_rate": round(_TOKEN_CACHE_HITS / looked_up, 4) if looked_up else None,
            "ttl_skew_seconds": _TOKEN_EXPIRY_SKEW_SECONDS,
        }


def _cached_token(cache_key: str) -> str:
    global _TOKEN_CACHE_HITS, _TOKEN_CACHE_MISSES
    with _TOKEN_CACHE_LOCK:
        token, expires_at = _TOKEN_CACHE.get(cache_key, ("", 0.0))
        fresh = bool(token) and time.time() < expires_at - _TOKEN_EXPIRY_SKEW_SECONDS
        if fresh:
            _TOKEN_CACHE_HITS += 1
        else:
            _TOKEN_CACHE_MISSES += 1
    return token if fresh else ""


async def _cloud_token(accounts: AccountStore, account_id: str) -> str:
    """Mint (or reuse) an m365.cloud.microsoft access token for one account."""
    account = accounts.get(account_id)
    if account is None:
        raise CloudSessionError("account not found")
    if getattr(account, "provider", "m365") != "m365":
        raise CloudSessionError("cloud conversations are M365-only (this account is personal Copilot)")
    rt = (getattr(account, "refresh_token", "") or "").strip()
    if not rt:
        raise CloudSessionError("no refresh token stored for this account; push a token from the user page first")
    binding = _stored_binding(account)
    if binding is None:
        raise CloudSessionError("stored refresh token has no verified client/authority/subject binding")
    client_id, authority, tenant_id, object_id = binding

    # Cache key carries the identity, so an account rebound to a different
    # Microsoft user can never keep listing/deleting the previous user's
    # conversations from a still-unexpired cached token.
    cache_key = f"{account_id}:{object_id}"
    cached = _cached_token(cache_key)
    if cached:
        return cached

    try:
        # Same poster as the substrate/media hops: it redeems the RT with the
        # client that issued it and only sends the SPA Origin header for the SPA
        # client (a native-client redemption must not carry it).
        resp = await _post_token(
            authority=authority,
            client_id=client_id,
            refresh_token=rt,
            scope=_CLOUD_SCOPE,
        )
    except Exception as exc:  # noqa: BLE001 - any transport error is just "unavailable"
        raise CloudSessionError(f"token exchange failed: {exc}") from exc
    if resp.status_code != 200:
        raise CloudSessionError(f"token exchange failed: HTTP {resp.status_code}")
    try:
        payload = resp.json()
        token = str(payload.get("access_token") or "")
        claims = decode_jwt_payload(token) if token else {}
    except Exception as exc:  # noqa: BLE001
        raise CloudSessionError(f"token exchange returned an unusable response: {exc}") from exc
    if not token:
        raise CloudSessionError("token exchange returned no access_token")
    # Same subject check the substrate path makes: never act on a conversation
    # list belonging to a different Microsoft identity than this account.
    if (
        normalize_microsoft_id(claims.get("tid")) != tenant_id
        or normalize_microsoft_id(claims.get("oid")) != object_id
    ):
        raise CloudSessionError("token exchange returned a different Microsoft identity")

    expires_at = float(claims.get("exp") or 0) or time.time() + 300
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE[cache_key] = (token, expires_at)
    return token


async def _cloud_action(token: str, action: str, state: dict | None = None, **extra) -> dict:
    """POST one SPA action and return its JSON body."""
    import httpx

    body = {"action": action, "state": state or {}, **extra}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": _ORIGIN,
        "Referer": f"{_ORIGIN}/",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(_CHAT_URL, json=body, headers=headers)
    except Exception as exc:  # noqa: BLE001
        raise CloudSessionError(f"{action} failed: {exc}") from exc
    if resp.status_code < 200 or resp.status_code >= 300:
        retry_after = resp.headers.get("Retry-After", "")
        suffix = f" (retry after {retry_after}s)" if retry_after else ""
        raise CloudSessionError(f"{action} failed: HTTP {resp.status_code}{suffix}")
    try:
        parsed = resp.json()
    except Exception as exc:  # noqa: BLE001 - Cloudflare/login HTML lands here
        raise CloudSessionError(f"{action} returned a non-JSON response") from exc
    if not isinstance(parsed, dict):
        raise CloudSessionError(f"{action} returned an unexpected response shape")
    return parsed


def _parse_chats(result: dict) -> list[dict]:
    store = result.get("store")
    if not isinstance(store, dict):
        raise CloudSessionError("RefreshNavPane returned no store (protocol changed?)")
    history = store.get("conversationPageHistoryList")
    chats = history.get("chats") if isinstance(history, dict) else None
    if not isinstance(chats, list):
        return []  # empty nav pane is a legitimate state
    parsed: list[dict] = []
    for raw in chats:
        if isinstance(raw, str):
            # The SPA sends each row either as an object or as embedded JSON.
            try:
                raw = json.loads(raw)
            except ValueError:
                continue
        if isinstance(raw, dict) and str(raw.get("conversationId") or "").strip():
            parsed.append(raw)
    return parsed


def chat_id(chat: dict) -> str:
    return str(chat.get("conversationId") or "").strip()


def chat_updated_at(chat: dict) -> float:
    """Best-effort seconds-epoch for a cloud row (its times are ms)."""
    for field in ("updateTimeUtc", "createTimeUtc"):
        try:
            value = float(chat.get(field) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value / 1000.0
    return 0.0


def chat_created_at(chat: dict) -> float:
    try:
        return float(chat.get("createTimeUtc") or 0) / 1000.0
    except (TypeError, ValueError):
        return 0.0


async def list_conversations(accounts: AccountStore, account_id: str) -> list[dict]:
    """One screen of the account's cloud conversation history (newest first)."""
    token = await _cloud_token(accounts, account_id)
    chats = _parse_chats(await _cloud_action(token, "RefreshNavPane"))
    return sorted(chats, key=chat_updated_at, reverse=True)


async def delete_conversation(accounts: AccountStore, account_id: str, conversation_id: str) -> None:
    token = await _cloud_token(accounts, account_id)
    await _cloud_action(
        token,
        "DeleteConversation",
        state={"conversationPageHistoryList": {"chats": []}},
        conversationId=conversation_id,
    )


async def cleanup_conversations(
    accounts: AccountStore,
    account_id: str,
    older_than: float = 0.0,
    keep_newest: int = 0,
    protected: set[str] | None = None,
) -> tuple[int, list[str]]:
    """Delete cloud conversations by age and/or count, newest kept first.

    `older_than` is seconds since the conversation was last updated and
    `keep_newest` is a count cap; 0 disables that rule, so passing neither
    deletes nothing. Ids in `protected` are the whitelist and are never touched.
    Returns (deleted_count, deleted_ids).
    """
    whitelist = set(protected or set())
    kept: set[str] = set()
    deleted: list[str] = []
    for _round in range(_CLEANUP_MAX_ROUNDS):
        chats = await list_conversations(accounts, account_id)
        pending = [
            chat
            for chat in chats
            if chat_id(chat) and chat_id(chat) not in whitelist and chat_id(chat) not in kept
        ]
        if not pending:
            break
        round_deleted = 0
        now = time.time()
        for chat in pending:  # already newest-first, so the cap keeps the newest
            cid = chat_id(chat)
            updated = chat_updated_at(chat)
            too_old = older_than > 0 and updated > 0 and now - updated > older_than
            over_cap = keep_newest > 0 and len(kept) >= keep_newest
            if not too_old and not over_cap:
                kept.add(cid)
                continue
            try:
                await delete_conversation(accounts, account_id, cid)
            except CloudSessionError as exc:
                elog(f"Cloud cleanup: cannot delete {cid} on {account_id}: {exc}")
                kept.add(cid)  # do not retry it in the next round
                continue
            deleted.append(cid)
            round_deleted += 1
        if not round_deleted:
            break  # nothing moved, so re-listing cannot reveal anything new
    return len(deleted), deleted
