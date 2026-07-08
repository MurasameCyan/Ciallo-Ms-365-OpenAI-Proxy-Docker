from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from urllib.parse import parse_qsl, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from .media_proxy import (
    is_allowed_m365_media_url,
    make_signed_media_proxy_url,
    rewrite_m365_media_urls,
    verify_signed_media_proxy_params,
)
from .media_proxy_events import append_media_proxy_event
from .refresh_scheduler import UpstreamMediaNotFound


def request_media_rewriter(app: FastAPI, request: Request):
    account = getattr(request.state, "account", None)
    account_id = getattr(account, "id", None)
    base_url = str(request.base_url).rstrip("/")
    secret = str(getattr(app.state, "media_proxy_secret", "") or "")

    def rewrite(text: str) -> str:
        suffixes = dict(getattr(app.state, "runtime_settings", {}) or {}).get("media_proxy_suffixes")
        return rewrite_m365_media_urls(text, base_url=base_url, account_id=account_id, secret=secret, allowed_suffixes=suffixes)

    return rewrite


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
        suffixes = dict(getattr(app.state, "runtime_settings", {}) or {}).get("media_proxy_suffixes")
        if not is_allowed_m365_media_url(source_url, suffixes):
            emit("blocked_source", source_host=parsed.netloc, source_path=parsed.path)
            raise HTTPException(status_code=400, detail="Unsupported media host")
        account = app.state.account_store.get(account_id)
        if account is None:
            emit("account_missing", source_host=parsed.netloc, source_path=parsed.path)
            raise HTTPException(status_code=404, detail="Account not found")
        fetcher = getattr(app.state.refresh_scheduler, "fetch_image", None)
        if fetcher is None:
            emit("fetcher_missing", source_host=parsed.netloc, source_path=parsed.path)
            raise HTTPException(status_code=503, detail="Media fetcher is unavailable")
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
        except Exception as exc:
            emit("error", error_type=type(exc).__name__, error=str(exc), duration_ms=round((time.perf_counter() - started) * 1000))
            raise HTTPException(status_code=502, detail=f"Media fetch failed: {exc}") from exc
        emit("ok", content_type=content_type or "application/octet-stream", bytes=len(content), duration_ms=round((time.perf_counter() - started) * 1000))
        return Response(
            content=content,
            media_type=content_type or "application/octet-stream",
            headers={"Cache-Control": "private, max-age=600", "X-Media-Proxy-Trace": trace_id},
        )
