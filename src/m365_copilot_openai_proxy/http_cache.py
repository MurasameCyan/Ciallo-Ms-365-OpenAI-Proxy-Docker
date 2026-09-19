"""What a response may be stored as, and what a repeat request costs.

WHY THIS EXISTS. Every JSON body this proxy serves carries conversation content,
a session-to-conversation mapping or account data. A 200 that declares no expiry
at all lets a cache assign its own freshness to that body (RFC 9111), so the
default here is an explicit refusal rather than a missing rule -- and it is a
default, not a fixed header: a handler serving a cacheable body declares its own
rule first and keeps it.

`/v1/models` is the one body a caller may hold. Its rule is `private` rather
than `public` because the catalogue varies by key (a per-key planning mode) and
by account provider, so a SHARED cache must not reuse one caller's list for
another. Its validator is a strong tag over the exact bytes that go out, so two
identical requests share it -- which is why the route stamps `created` once per
process instead of per request.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import Request
from fastapi.responses import Response
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The one rule this module grants. A caller may hold the model catalogue, but
# only its own copy.
MODELS_CACHE_CONTROL = "private, max-age=300"


def content_etag(body: bytes) -> str:
    """A strong validator derived from the bytes that go out.

    RFC 7232 requires the double quotes; a cache that parses the header
    properly ignores a tag without them.
    """
    return '"' + hashlib.sha256(body).hexdigest() + '"'


def if_none_match_matches(header_value: str, etag: str) -> bool:
    """Whether an If-None-Match field value accepts `etag` (RFC 9110 13.1.2).

    Comparison is weak: a `W/` prefix is stripped on both sides, because a
    validator answered with 304 only has to be semantically equivalent. `*`
    matches anything, and a caller may send a set.
    """
    if not header_value:
        return False
    for candidate in header_value.split(","):
        candidate = candidate.strip()
        if not candidate:
            continue
        if candidate == "*":
            return True
        if candidate[:2] in ("W/", "w/"):
            candidate = candidate[2:].strip()
        if candidate == etag:
            return True
    return False


def cached_json_response(request: Request, payload: dict, cache_control: str) -> Response:
    """Serialize once, then answer a matching revalidation with a bodiless 304.

    The body is marshalled here rather than by a JSONResponse so the tag
    describes exactly the bytes that leave. `allow_nan=False` matches Starlette's
    own writer: a non-finite float must not go out as invalid JSON.
    """
    body = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    etag = content_etag(body)
    headers = {"ETag": etag, "Cache-Control": cache_control}
    if if_none_match_matches(request.headers.get("if-none-match", ""), etag):
        # Starlette leaves content-length/content-type off a 304 on its own.
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


class DefaultNoStoreMiddleware:
    """Refuse cache storage on any response that declares no rule of its own.

    Pure-ASGI rather than ``app.middleware("http")``: this wraps every response
    in the app, SSE included, and BaseHTTPMiddleware would interpose a task and
    a queue per chunk on a stream that already has a write deadline to honour.
    The header is set on ``http.response.start`` only, before anything is sent,
    so a stream's headers are never touched mid-body.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # A CORS preflight is answered by the CORS layer and cached under its own
        # Access-Control-Max-Age; a refusal here would fight that rule.
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        async def send_with_refusal(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "cache-control" not in headers:
                    headers["cache-control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_refusal)
