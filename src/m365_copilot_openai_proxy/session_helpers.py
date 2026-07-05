from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from fastapi import Request

from .models import AnthropicMessagesRequest, OpenAIChatRequest, OpenAIResponsesRequest
from .session_store import PersistentSession
from .translator import flatten_content

_PERSIST_MODEL_SUFFIX = ":persist"
_SESSION_ID_HEADER = "x-m365-session-id"


def _detect_conversation_session(request: OpenAIChatRequest) -> tuple[str, str]:
    for msg in request.messages:
        if msg.role == "user":
            text = flatten_content(msg.content).strip()
            if text:
                sid = "conv_" + hashlib.sha256(text.encode()).hexdigest()[:12]
                title = text[:60].replace("\n", " ")
                return sid, title
    return "conv_" + uuid.uuid4().hex[:12], "New conversation"


def _responses_session_key(request: OpenAIResponsesRequest) -> str | None:
    user = getattr(request, "user", None)
    if isinstance(user, str) and user.strip():
        return user.strip()
    text = json.dumps(request.input, ensure_ascii=False, sort_keys=True)
    if text:
        return "responses_" + hashlib.sha256(text.encode()).hexdigest()[:12]
    return None


def _messages_session_key(request: AnthropicMessagesRequest) -> str | None:
    for msg in request.messages:
        if msg.role == "user":
            text = flatten_content(msg.content).strip()
            if text:
                return "messages_" + hashlib.sha256(text.encode()).hexdigest()[:12]
    return None


def _persistent_session(
    app: Any,
    raw_request: Request,
    model: str,
    fallback_key: str | None = None,
    request: OpenAIChatRequest | AnthropicMessagesRequest | None = None,
) -> PersistentSession | None:
    key_obj = getattr(raw_request.state, "api_key_obj", None)
    account = getattr(raw_request.state, "account", None)
    tenant = (key_obj.id if key_obj is not None else None) or (account.id if account is not None else "global")
    header_key = (raw_request.headers.get(_SESSION_ID_HEADER) or "").strip()
    if header_key:
        return app.state.session_store.get(f"{tenant}:header:{header_key}")
    if model.endswith(_PERSIST_MODEL_SUFFIX):
        return app.state.session_store.get(f"{tenant}:model:{fallback_key or 'default'}")
    if request is not None:
        sid, _title = _detect_conversation_session(request)
        has_assistant = any(m.role == "assistant" for m in request.messages)
        if not has_assistant:
            return app.state.session_store.reset(f"{tenant}:auto:{sid}")
        return app.state.session_store.get(f"{tenant}:auto:{sid}")
    if fallback_key:
        return app.state.session_store.get(f"{tenant}:auto:{fallback_key}")
    return None
