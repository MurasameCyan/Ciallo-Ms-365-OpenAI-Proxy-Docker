"""Session management endpoints: the local session table merged with the M365
cloud conversation history.

Two audiences, one implementation:
  * ``/admin/sessions*`` sees every tenant, with an optional ``key_id`` filter so
    the admin page can switch between "all users" and one user.
  * ``/user/sessions*`` is pinned to the caller's own tenant prefix.

A cloud conversation belongs to the *account*, and several users can share one
account, so the user-facing views only ever expose cloud rows that match one of
the caller's own sessions. Otherwise one user could read (and delete) a
colleague's conversations just because they were issued keys on the same M365
account.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from fastapi import FastAPI, Request

from .key_store import ApiKey
from .m365_cloud_client import (
    CloudSessionError,
    chat_created_at,
    chat_id,
    chat_updated_at,
    cleanup_conversations,
    delete_conversation,
    list_conversations,
)
from .response_helpers import _json_err
from .routes_user import resolve_bearer_key
from .runtime_flags import elog

_MAX_KEEP_IDS = 200
_MAX_TTL_HOURS = 24 * 365
_MAX_KEEP = 1000


async def _body(request: Request) -> dict:
    try:
        parsed = await request.json()
    except Exception:  # noqa: BLE001 - a malformed body is just "no options"
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _cleanup_options(body: dict) -> tuple[float, int, set[str]]:
    """(older_than_seconds, keep_newest, whitelist) from a cleanup request."""
    try:
        ttl_hours = min(max(float(body.get("ttl_hours") or 0), 0.0), _MAX_TTL_HOURS)
    except (TypeError, ValueError):
        ttl_hours = 0.0
    try:
        keep = min(max(int(body.get("keep") or 0), 0), _MAX_KEEP)
    except (TypeError, ValueError):
        keep = 0
    raw_ids = body.get("keep_ids")
    keep_ids = {
        str(item).strip()
        for item in (raw_ids if isinstance(raw_ids, list) else [])
        if str(item).strip()
    }
    return ttl_hours * 3600, keep, set(list(keep_ids)[:_MAX_KEEP_IDS])


def register_session_routes(app: FastAPI, require_admin: Callable[[Request], object | None]) -> None:
    def _tenant_meta(tenant: str) -> dict:
        """Who a session store tenant prefix belongs to.

        A tenant is an api key id for keyed traffic, an account id for the
        legacy single-account mode, or "global" when neither applies.
        """
        key = app.state.key_store.get(tenant)
        account_id = key.account_id if key is not None else tenant
        account = app.state.account_store.get(account_id) if account_id else None
        return {
            "key_id": key.id if key is not None else "",
            "key_name": key.name if key is not None else "",
            "username": key.username if key is not None else "",
            "account_id": account.id if account is not None else "",
            "account_name": account.name if account is not None else "",
            "account_email": (account.email or "") if account is not None else "",
        }

    def _local_rows(prefix: str) -> list[dict]:
        rows: list[dict] = []
        meta_cache: dict[str, dict] = {}
        for store_key, session in app.state.session_store.items():
            if prefix and not store_key.startswith(prefix):
                continue
            tenant, _, rest = store_key.partition(":")
            kind, _, session_id = rest.partition(":")
            meta = meta_cache.setdefault(tenant, _tenant_meta(tenant))
            rows.append({
                "store_key": store_key,
                "tenant": tenant,
                "kind": kind or "auto",
                "session_id": session_id,
                "conversation_id": session.conversation_id,
                "turn_count": session.turn_count,
                "last_accessed": session.last_accessed,
                "created_at": 0.0,
                "updated_at": session.last_accessed,
                "chat_name": "",
                "source": "local",
                **meta,
            })
        return rows

    async def _cloud_by_account(account_ids: set[str]) -> tuple[dict[str, list[dict]], list[str]]:
        """Cloud conversation lists per account, plus one warning per account
        whose cloud management is unavailable (no verified refresh token, HTTP
        error, ...). A failure never hides the local rows."""
        ordered = sorted(account_ids)
        results = await asyncio.gather(
            *(list_conversations(app.state.account_store, account_id) for account_id in ordered),
            return_exceptions=True,
        )
        chats: dict[str, list[dict]] = {}
        notes: list[str] = []
        for account_id, result in zip(ordered, results):
            if isinstance(result, CloudSessionError):
                account = app.state.account_store.get(account_id)
                label = (account.email or account.name or account_id) if account is not None else account_id
                notes.append(f"{label}: {result}")
                continue
            if isinstance(result, BaseException):
                elog(f"Cloud conversation list failed for {account_id}: {result!r}")
                notes.append(f"{account_id}: {result}")
                continue
            chats[account_id] = result
        return chats, notes

    async def _sessions_payload(
        prefix: str,
        account_ids: set[str],
        cloud: bool,
        include_unmatched_cloud: bool,
    ) -> dict:
        rows = _local_rows(prefix)
        notes: list[str] = []
        if cloud and account_ids:
            chats, notes = await _cloud_by_account(account_ids)
            by_id = {
                (account_id, chat_id(chat)): chat
                for account_id, account_chats in chats.items()
                for chat in account_chats
            }
            for row in rows:
                chat = by_id.pop((row["account_id"], row["conversation_id"]), None)
                if chat is None:
                    continue
                row["source"] = "both"
                row["chat_name"] = str(chat.get("chatName") or "")
                row["created_at"] = chat_created_at(chat)
                row["updated_at"] = chat_updated_at(chat) or row["updated_at"]
            if include_unmatched_cloud:
                for (account_id, conversation_id), chat in by_id.items():
                    account = app.state.account_store.get(account_id)
                    rows.append({
                        "store_key": "",
                        "tenant": "",
                        "kind": "cloud",
                        "session_id": "",
                        "conversation_id": conversation_id,
                        "turn_count": 0,
                        "last_accessed": 0.0,
                        "created_at": chat_created_at(chat),
                        "updated_at": chat_updated_at(chat),
                        "chat_name": str(chat.get("chatName") or ""),
                        "source": "cloud",
                        "key_id": "",
                        "key_name": "",
                        "username": "",
                        "account_id": account_id,
                        "account_name": account.name if account is not None else "",
                        "account_email": (account.email or "") if account is not None else "",
                    })
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        return {
            "object": "list",
            "data": rows,
            "count": len(rows),
            "cloud": bool(cloud and account_ids),
            "warnings": notes,
        }

    def _account_ids_for_keys(keys: list[ApiKey]) -> set[str]:
        return {k.account_id for k in keys if k.account_id}

    async def _delete_one(
        store_key: str,
        conversation_id: str,
        account_id: str,
        cloud: bool,
        prefix: str,
    ) -> dict:
        """Delete a session locally and (optionally) its cloud conversation.

        Deleting the cloud conversation always clears the matching local
        binding(s) too: the upstream thread is gone, so a session still pointing
        at it would fail every continuation.
        """
        notes: list[str] = []
        deleted_cloud = False
        if cloud and conversation_id and account_id:
            try:
                await delete_conversation(app.state.account_store, account_id, conversation_id)
                deleted_cloud = True
            except CloudSessionError as exc:
                notes.append(str(exc))
        removed: list[str] = []
        if store_key and app.state.session_store.remove(store_key):
            removed.append(store_key)
        if deleted_cloud and conversation_id:
            for key, session in app.state.session_store.items():
                if (
                    key != store_key
                    and session.conversation_id == conversation_id
                    and key.startswith(prefix)
                    and app.state.session_store.remove(key)
                ):
                    removed.append(key)
        return {
            "removed_local": removed,
            "deleted_cloud": deleted_cloud,
            "warnings": notes,
        }

    async def _cleanup(
        prefix: str,
        account_ids: set[str],
        cloud: bool,
        older_than: float,
        keep_newest: int,
        keep_ids: set[str],
    ) -> dict:
        """TTL + count-cap cleanup with a whitelist, local then cloud.

        `keep_ids` may hold store keys (local) and conversation ids (cloud). The
        cloud pass additionally protects every conversation the surviving local
        sessions still point at, so cleaning up abandoned cloud history can
        never break a conversation that is still in use.
        """
        removed = app.state.session_store.prune(
            prefix=prefix,
            older_than=older_than,
            keep_newest=keep_newest,
            protected=keep_ids,
        )
        notes: list[str] = []
        deleted_cloud: list[str] = []
        if cloud and account_ids:
            live = {
                session.conversation_id
                for key, session in app.state.session_store.items()
                if not prefix or key.startswith(prefix)
            }
            protected = keep_ids | live
            for account_id in sorted(account_ids):
                try:
                    _count, ids = await cleanup_conversations(
                        app.state.account_store,
                        account_id,
                        older_than=older_than,
                        keep_newest=keep_newest,
                        protected=protected,
                    )
                    deleted_cloud.extend(ids)
                except CloudSessionError as exc:
                    account = app.state.account_store.get(account_id)
                    label = (account.email or account.name or account_id) if account is not None else account_id
                    notes.append(f"{label}: {exc}")
        return {
            "removed_local": removed,
            "deleted_cloud": deleted_cloud,
            "warnings": notes,
        }

    def _wants_cloud(value: str | None, default: bool = True) -> bool:
        if value is None or value == "":
            return default
        return value.strip().lower() not in ("0", "false", "no", "off")

    # ---------------------------------------------------------------- admin
    @app.get("/admin/sessions")
    async def admin_list_sessions(request: Request):
        err = require_admin(request)
        if err: return err
        key_id = (request.query_params.get("key_id") or "all").strip()
        cloud = _wants_cloud(request.query_params.get("cloud"))
        if key_id and key_id != "all":
            key = app.state.key_store.get(key_id)
            if key is None:
                return _json_err(404, "Unknown user")
            return await _sessions_payload(
                prefix=f"{key.id}:",
                account_ids=_account_ids_for_keys([key]),
                cloud=cloud,
                include_unmatched_cloud=True,
            )
        return await _sessions_payload(
            prefix="",
            account_ids={a.id for a in app.state.account_store.list()},
            cloud=cloud,
            include_unmatched_cloud=True,
        )

    @app.post("/admin/sessions/delete")
    async def admin_delete_session(request: Request):
        err = require_admin(request)
        if err: return err
        body = await _body(request)
        store_key = str(body.get("store_key") or "").strip()
        conversation_id = str(body.get("conversation_id") or "").strip()
        account_id = str(body.get("account_id") or "").strip()
        cloud = bool(body.get("cloud", True))
        if not store_key and not conversation_id:
            return _json_err(400, "store_key or conversation_id is required")
        if store_key:
            session = app.state.session_store.get_existing(store_key)
            if session is None:
                return _json_err(404, "Unknown session")
            conversation_id = conversation_id or session.conversation_id
            if not account_id:
                account_id = _tenant_meta(store_key.partition(":")[0])["account_id"]
        return await _delete_one(store_key, conversation_id, account_id, cloud, prefix="")

    @app.post("/admin/sessions/cleanup")
    async def admin_cleanup_sessions(request: Request):
        err = require_admin(request)
        if err: return err
        body = await _body(request)
        key_id = str(body.get("key_id") or "all").strip()
        cloud = bool(body.get("cloud", True))
        older_than, keep_newest, keep_ids = _cleanup_options(body)
        if key_id and key_id != "all":
            key = app.state.key_store.get(key_id)
            if key is None:
                return _json_err(404, "Unknown user")
            return await _cleanup(
                f"{key.id}:", _account_ids_for_keys([key]), cloud, older_than, keep_newest, keep_ids
            )
        return await _cleanup(
            "",
            {a.id for a in app.state.account_store.list()},
            cloud,
            older_than,
            keep_newest,
            keep_ids,
        )

    # ----------------------------------------------------------------- user
    def _caller(request: Request) -> ApiKey | None:
        return resolve_bearer_key(app, request)

    @app.get("/user/sessions")
    async def user_list_sessions(request: Request):
        key = _caller(request)
        if key is None:
            return _json_err(401, "Invalid API key", "auth_error")
        cloud = _wants_cloud(request.query_params.get("cloud"))
        return await _sessions_payload(
            prefix=f"{key.id}:",
            account_ids=_account_ids_for_keys([key]),
            cloud=cloud,
            # Cloud rows with no local session may belong to another user on the
            # same shared account, so a user never sees them.
            include_unmatched_cloud=False,
        )

    @app.post("/user/sessions/delete")
    async def user_delete_session(request: Request):
        key = _caller(request)
        if key is None:
            return _json_err(401, "Invalid API key", "auth_error")
        body = await _body(request)
        store_key = str(body.get("store_key") or "").strip()
        if not store_key.startswith(f"{key.id}:"):
            return _json_err(404, "Unknown session")
        session = app.state.session_store.get_existing(store_key)
        if session is None:
            return _json_err(404, "Unknown session")
        # The conversation id comes from the caller's own session, never from the
        # body: on a shared account that would let a user delete someone else's
        # cloud conversation.
        return await _delete_one(
            store_key,
            session.conversation_id,
            key.account_id,
            bool(body.get("cloud", True)),
            prefix=f"{key.id}:",
        )

    @app.post("/user/sessions/cleanup")
    async def user_cleanup_sessions(request: Request):
        key = _caller(request)
        if key is None:
            return _json_err(401, "Invalid API key", "auth_error")
        body = await _body(request)
        cloud = bool(body.get("cloud", True))
        older_than, keep_newest, keep_ids = _cleanup_options(body)
        prefix = f"{key.id}:"
        # Cloud side is deliberately not the account-wide sweep the admin gets:
        # only the conversations of the sessions this cleanup just dropped are
        # deleted upstream, so a shared account keeps other users' history.
        doomed = {
            session.conversation_id: store_key
            for store_key, session in app.state.session_store.items()
            if store_key.startswith(prefix)
        }
        removed = app.state.session_store.prune(
            prefix=prefix,
            older_than=older_than,
            keep_newest=keep_newest,
            protected=keep_ids,
        )
        removed_set = set(removed)
        notes: list[str] = []
        deleted_cloud: list[str] = []
        if cloud and key.account_id:
            for conversation_id, store_key in doomed.items():
                if store_key not in removed_set or conversation_id in keep_ids:
                    continue
                try:
                    await delete_conversation(app.state.account_store, key.account_id, conversation_id)
                    deleted_cloud.append(conversation_id)
                except CloudSessionError as exc:
                    notes.append(str(exc))
                    break  # one broken account fails them all; do not hammer it
        return {
            "removed_local": removed,
            "deleted_cloud": deleted_cloud,
            "warnings": notes,
        }
