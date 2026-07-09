from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from urllib.parse import parse_qsl, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from .media_proxy import (
    asyncgw_object_fetch_url,
    content_disposition_for_media,
    is_allowed_m365_media_url,
    rewrite_m365_media_urls,
    verify_signed_media_proxy_params,
)
from .media_proxy_events import append_media_proxy_event
from .refresh_scheduler import UpstreamMediaNotFound


_GLOBAL_MEDIA_ACCOUNT_ID = "__global__"


def _body_preview(content: bytes, limit: int = 300) -> str:
    return content[:limit].decode("utf-8", errors="replace")


def _allowed_media_suffixes(app: FastAPI) -> list[str]:
    """Union of the global runtime suffixes and every per-user override.

    Signed URLs are minted with either the global list or a user's override, so
    the fetch-side allow-check (defence-in-depth on top of the HMAC signature)
    must accept any suffix that any user is permitted to sign, otherwise a
    user's custom suffix would sign successfully yet be rejected here.
    """
    suffixes: list[str] = []
    seen: set[str] = set()
    runtime = dict(getattr(app.state, "runtime_settings", {}) or {})
    for suffix in (runtime.get("media_proxy_suffixes") or []):
        if suffix not in seen:
            seen.add(suffix)
            suffixes.append(suffix)
    key_store = getattr(app.state, "key_store", None)
    if key_store is not None:
        for k in key_store.list():
            for suffix in (getattr(k, "media_proxy_suffixes", []) or []):
                if suffix not in seen:
                    seen.add(suffix)
                    suffixes.append(suffix)
    return suffixes


def request_media_rewriter(app: FastAPI, request: Request):
    account = getattr(request.state, "account", None)
    account_id = getattr(account, "id", None)
    if account_id is None and getattr(app.state, "token_store", None) is not None and app.state.token_store.get():
        account_id = _GLOBAL_MEDIA_ACCOUNT_ID
    base_url = str(request.base_url).rstrip("/")
    secret = str(getattr(app.state, "media_proxy_secret", "") or "")
    key_obj = getattr(request.state, "api_key_obj", None)
    user_suffixes = list(getattr(key_obj, "media_proxy_suffixes", []) or [])

    def rewrite(text: str) -> str:
        runtime = dict(getattr(app.state, "runtime_settings", {}) or {})
        # A non-empty per-user override fully replaces the global suffixes for
        # this user's signed URLs; empty falls back to the global runtime list.
        suffixes = user_suffixes if user_suffixes else runtime.get("media_proxy_suffixes")
        ttl_seconds = runtime.get("media_proxy_ttl_seconds")
        return rewrite_m365_media_urls(text, base_url=base_url, account_id=account_id, secret=secret, allowed_suffixes=suffixes, ttl_seconds=ttl_seconds)

    return rewrite


async def _fetch_global_media(app: FastAPI, source_url: str, emit) -> tuple[bytes, str]:
    token = app.state.token_store.get() if getattr(app.state, "token_store", None) is not None else ""
    if not token:
        emit("global_token_missing")
        raise RuntimeError("global M365 token is unavailable")
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,audio/*,video/*,*/*;q=0.8",
        "Referer": "https://designerapp.officeapps.live.com/",
    }
    # Strip the model-supplied display filename; asyncgw serves the object at the
    # bare /views/original path and 404s when the trailing filename is present.
    fetch_url = asyncgw_object_fetch_url(source_url)
    if fetch_url != source_url:
        emit("asyncgw_url_normalized", original_path=urlsplit(source_url).path, fetch_path=urlsplit(fetch_url).path)
    emit("global_direct_start", token_header=True)
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        response = await client.get(fetch_url, headers=headers)
    response_url = urlsplit(str(response.url))
    fields = {
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "bytes": len(response.content),
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "response_host": response_url.hostname or "",
        "response_path": response_url.path,
        "www_authenticate": response.headers.get("www-authenticate", ""),
    }
    if response.status_code >= 400:
        fields["body_preview"] = _body_preview(response.content)
    emit("global_direct_response", **fields)
    if response.status_code == 404:
        raise UpstreamMediaNotFound("upstream media returned HTTP 404")
    if response.status_code >= 400:
        raise RuntimeError(f"upstream media returned HTTP {response.status_code}")
    return response.content, response.headers.get("content-type", "application/octet-stream")


def register_media_proxy_routes(app: FastAPI) -> None:
    @app.get("/v1/m365-media")
    async def m365_media(account_id: str, u: str, exp: str, sig: str):
        trace_id = f"med_{uuid.uuid4().hex[:12]}"
        started = time.perf_counter()

        def emit(phase: str, **fields):
            append_media_proxy_event(app.state, trace_id, phase, account_id=account_id, **fields)

        secret = str(getattr(app.state, "media_proxy_secret", "") or "")
        emit("request")
        source_url = verify_signed_media_proxy_params(account_id, u, exp, sig, secret)
        if source_url is None:
            now = int(time.time())
            try:
                expires_at = int(exp)
            except ValueError:
                expires_at = 0
            emit("invalid_signature", exp=exp, now=now, expired=bool(expires_at and expires_at < now))
            raise HTTPException(status_code=403, detail="Invalid media proxy signature")
        parsed = urlsplit(source_url)
        suffixes = _allowed_media_suffixes(app)
        if not is_allowed_m365_media_url(source_url, suffixes):
            emit("blocked_source", source_host=parsed.netloc, source_path=parsed.path)
            raise HTTPException(status_code=400, detail="Unsupported media host")
        timeout = float(getattr(app.state, "media_proxy_timeout", 20.0) or 20.0)
        query_keys = sorted({key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)})
        emit(
            "fetch_start",
            source_host=parsed.hostname or "",
            source_path=parsed.path,
            source_query_keys=query_keys,
            has_file_token="fileToken" in query_keys,
            has_path="path" in query_keys,
            timeout_seconds=timeout,
        )
        try:
            if account_id == _GLOBAL_MEDIA_ACCOUNT_ID:
                content, content_type = await asyncio.wait_for(_fetch_global_media(app, source_url, emit), timeout=timeout)
            else:
                account = app.state.account_store.get(account_id)
                if account is None:
                    emit("account_missing", source_host=parsed.netloc, source_path=parsed.path)
                    raise HTTPException(status_code=404, detail="Account not found")
                fetcher = getattr(app.state.refresh_scheduler, "fetch_image", None)
                if fetcher is None:
                    emit("fetcher_missing", source_host=parsed.netloc, source_path=parsed.path)
                    raise HTTPException(status_code=503, detail="Media fetcher is unavailable")
                kwargs = {}
                if "event_sink" in inspect.signature(fetcher).parameters:
                    kwargs["event_sink"] = emit
                content, content_type = await asyncio.wait_for(fetcher(account_id, source_url, **kwargs), timeout=timeout)
        except asyncio.TimeoutError as exc:
            emit("timeout", duration_ms=round((time.perf_counter() - started) * 1000))
            raise HTTPException(status_code=504, detail="Media fetch timed out") from exc
        except UpstreamMediaNotFound as exc:
            emit("not_found", error_type=type(exc).__name__, error=str(exc), duration_ms=round((time.perf_counter() - started) * 1000))
            raise HTTPException(status_code=404, detail="Media not found") from exc
        except HTTPException:
            raise
        except Exception as exc:
            emit("error", error_type=type(exc).__name__, error=str(exc), duration_ms=round((time.perf_counter() - started) * 1000))
            raise HTTPException(status_code=502, detail=f"Media fetch failed: {exc}") from exc
        emit("ok", content_type=content_type or "application/octet-stream", bytes=len(content), duration_ms=round((time.perf_counter() - started) * 1000))
        return Response(
            content=content,
            media_type=content_type or "application/octet-stream",
            headers={
                "Cache-Control": "private, max-age=600",
                "X-Media-Proxy-Trace": trace_id,
                "Content-Disposition": content_disposition_for_media(source_url, content_type),
            },
        )
