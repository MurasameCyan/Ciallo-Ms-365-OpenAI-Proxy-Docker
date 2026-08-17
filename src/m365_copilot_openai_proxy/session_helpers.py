from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from typing import Any

from fastapi import Request

from .history_index import normalize_history
from .models import AnthropicMessagesRequest, OpenAIChatRequest, OpenAIResponsesRequest
from .session_store import PersistentSession
from .translator import flatten_content

_PERSIST_MODEL_SUFFIX = ":persist"
_SESSION_ID_HEADER = "x-m365-session-id"
_RESP_ID_PREFIX = "resp_"


def _request_tenant(raw_request: Request) -> str:
    key_obj = getattr(raw_request.state, "api_key_obj", None)
    account = getattr(raw_request.state, "account", None)
    return (
        (key_obj.id if key_obj is not None else None)
        or (account.id if account is not None else "global")
    )


def _detect_conversation_session(request: OpenAIChatRequest) -> tuple[str, str]:
    for msg in request.messages:
        if msg.role == "user":
            text = flatten_content(msg.content).strip()
            if text:
                sid = "conv_" + hashlib.sha256(text.encode()).hexdigest()[:12]
                title = text[:60].replace("\n", " ")
                return sid, title
    return "conv_" + uuid.uuid4().hex[:12], "New conversation"


def _encode_responses_session_id(
    session_key: str,
    secret: str | None = None,
    call_ids: set[str] | None = None,
) -> str:
    """Encode a session key into a Responses `resp_...` id so the client can
    echo it back as `previous_response_id` on the next turn. A random suffix
    keeps each id unique (per OpenAI semantics) while the encoded prefix stays
    stable across the conversation."""
    payload = json.dumps(
        {"session": session_key, "calls": sorted(call_ids or set())},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    nonce = uuid.uuid4().hex[:8]
    if not secret:
        return f"{_RESP_ID_PREFIX}{token}.{nonce}"
    signature = hmac.new(
        secret.encode(), f"{token}.{nonce}".encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{_RESP_ID_PREFIX}{token}.{nonce}.{signature}"


def _decode_responses_session_id(
    resp_id: str | None,
    secret: str | None = None,
) -> str | None:
    """Recover the session key previously encoded by
    `_encode_responses_session_id`. Returns None for ids that were not produced
    by us (e.g. plain random ids) so callers fall back to other keys."""
    if not isinstance(resp_id, str) or not resp_id.startswith(_RESP_ID_PREFIX):
        return None
    parts = resp_id[len(_RESP_ID_PREFIX):].split(".")
    token = parts[0] if parts else ""
    if not token:
        return None
    if secret:
        if len(parts) != 3:
            return None
        expected = hmac.new(
            secret.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(parts[2], expected):
            return None
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(decoded, str):
        return decoded or None
    session_key = decoded.get("session") if isinstance(decoded, dict) else None
    return session_key if isinstance(session_key, str) and session_key else None


def _decode_responses_response_claims(
    resp_id: str | None,
    secret: str,
) -> tuple[str, set[str]] | None:
    """Verify an issued Responses id and recover its session + tool call ids."""
    session_key = _decode_responses_session_id(resp_id, secret)
    if session_key is None or not isinstance(resp_id, str):
        return None
    token = resp_id[len(_RESP_ID_PREFIX):].split(".", 1)[0]
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    calls = decoded.get("calls") if isinstance(decoded, dict) else None
    if not isinstance(calls, list) or any(not isinstance(item, str) for item in calls):
        return None
    return session_key, set(calls)


def _responses_session_key(request: OpenAIResponsesRequest) -> str | None:
    prev = _decode_responses_session_id(getattr(request, "previous_response_id", None))
    if prev:
        return prev
    user = getattr(request, "user", None)
    if isinstance(user, str) and user.strip():
        return user.strip()
    text = json.dumps(request.input, ensure_ascii=False, sort_keys=True)
    if text:
        return "responses_" + hashlib.sha256(text.encode()).hexdigest()[:12]
    return None


def _responses_store_key(app: Any, session: PersistentSession | None) -> str | None:
    """Return the actual tenant-qualified store key selected for this request."""
    if session is None:
        return None
    return app.state.session_store.key_for(session)


def _responses_store_key_belongs_to_request(
    raw_request: Request,
    store_key: str,
) -> bool:
    return store_key.startswith(f"{_request_tenant(raw_request)}:")


def _messages_session_key(request: AnthropicMessagesRequest) -> str | None:
    for msg in request.messages:
        if msg.role == "user":
            text = flatten_content(msg.content).strip()
            if text:
                return "messages_" + hashlib.sha256(text.encode()).hexdigest()[:12]
    return None


def _auto_session(
    app: Any,
    tenant: str,
    request: OpenAIChatRequest | AnthropicMessagesRequest,
) -> PersistentSession:
    """Pick the session for a conversation the client did not name itself.

    Prefers the exact history index (longest strict prefix of the messages just
    sent), which keeps two conversations that open with the same text on separate
    upstream threads instead of resetting each other. Falls back to the legacy
    first-user-message key, so a client that trims old messages -- or a restart,
    which empties the in-memory index -- still lands on the session
    sessions.json restored.
    """
    index = getattr(app.state, "history_index", None)
    pairs = normalize_history(request.messages) if index is not None else []
    has_assistant = any(m.role == "assistant" for m in request.messages)
    if pairs and has_assistant:
        matched = index.match(tenant, pairs)
        if matched is not None:
            session = app.state.session_store.get_existing(matched)
            if session is not None:
                index.record(tenant, pairs, matched)
                return session
    sid, _title = _detect_conversation_session(request)
    key = f"{tenant}:auto:{sid}"
    if has_assistant:
        session = app.state.session_store.get(key)
    else:
        # A brand-new conversation must not evict the session another chain is
        # still running on (both opened with the same text), or that
        # conversation's next turn silently continues in this one's thread.
        if pairs and index.is_taken(tenant, key, pairs):
            key = f"{key}:{uuid.uuid4().hex[:8]}"
        session = app.state.session_store.reset(key)
    if pairs:
        index.record(tenant, pairs, key)
    return session


def _persistent_session(
    app: Any,
    raw_request: Request,
    model: str,
    fallback_key: str | None = None,
    request: OpenAIChatRequest | AnthropicMessagesRequest | None = None,
) -> PersistentSession | None:
    tenant = _request_tenant(raw_request)
    header_key = (raw_request.headers.get(_SESSION_ID_HEADER) or "").strip()
    if header_key:
        return app.state.session_store.get(f"{tenant}:header:{header_key}")
    if model.endswith(_PERSIST_MODEL_SUFFIX):
        return app.state.session_store.get(f"{tenant}:model:{fallback_key or 'default'}")
    if request is not None:
        return _auto_session(app, tenant, request)
    if fallback_key:
        return app.state.session_store.get(f"{tenant}:auto:{fallback_key}")
    return None
