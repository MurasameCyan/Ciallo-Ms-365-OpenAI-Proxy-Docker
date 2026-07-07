from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from .image_proxy import (
    is_allowed_m365_image_url,
    make_signed_image_proxy_url,
    rewrite_m365_image_urls,
    verify_signed_image_proxy_params,
)
from .image_proxy_events import append_image_proxy_event


def request_image_rewriter(app: FastAPI, request: Request):
    account = getattr(request.state, "account", None)
    account_id = getattr(account, "id", None)
    base_url = str(request.base_url).rstrip("/")
    secret = str(getattr(app.state, "image_proxy_secret", "") or "")

    def rewrite(text: str) -> str:
        return rewrite_m365_image_urls(text, base_url=base_url, account_id=account_id, secret=secret)

    return rewrite


def register_image_proxy_routes(app: FastAPI) -> None:
    @app.get("/v1/m365-image")
    async def m365_image(account_id: str, u: str, exp: str, sig: str):
        trace_id = f"img_{uuid.uuid4().hex[:12]}"
        started = time.perf_counter()

        def emit(phase: str, **fields):
            append_image_proxy_event(app.state, trace_id, phase, account_id=account_id, **fields)

        secret = str(getattr(app.state, "image_proxy_secret", "") or "")
        emit("request")
        source_url = verify_signed_image_proxy_params(account_id, u, exp, sig, secret)
        if source_url is None:
            emit("invalid_signature")
            raise HTTPException(status_code=403, detail="Invalid image proxy signature")
        parsed = urlsplit(source_url)
        if not is_allowed_m365_image_url(source_url):
            emit("blocked_source", source_host=parsed.netloc, source_path=parsed.path)
            raise HTTPException(status_code=400, detail="Unsupported image host")
        account = app.state.account_store.get(account_id)
        if account is None:
            emit("account_missing", source_host=parsed.netloc, source_path=parsed.path)
            raise HTTPException(status_code=404, detail="Account not found")
        fetcher = getattr(app.state.refresh_scheduler, "fetch_image", None)
        if fetcher is None:
            emit("fetcher_missing", source_host=parsed.netloc, source_path=parsed.path)
            raise HTTPException(status_code=503, detail="Image fetcher is unavailable")
        timeout = float(getattr(app.state, "image_proxy_timeout", 20.0) or 20.0)
        emit("fetch_start", source_host=parsed.netloc, source_path=parsed.path, timeout_seconds=timeout)
        try:
            kwargs = {}
            if "event_sink" in inspect.signature(fetcher).parameters:
                kwargs["event_sink"] = emit
            content, content_type = await asyncio.wait_for(fetcher(account_id, source_url, **kwargs), timeout=timeout)
        except asyncio.TimeoutError as exc:
            emit("timeout", duration_ms=round((time.perf_counter() - started) * 1000))
            raise HTTPException(status_code=504, detail="Image fetch timed out") from exc
        except Exception as exc:
            emit("error", error_type=type(exc).__name__, error=str(exc), duration_ms=round((time.perf_counter() - started) * 1000))
            raise HTTPException(status_code=502, detail=f"Image fetch failed: {exc}") from exc
        emit("ok", content_type=content_type or "application/octet-stream", bytes=len(content), duration_ms=round((time.perf_counter() - started) * 1000))
        return Response(
            content=content,
            media_type=content_type or "application/octet-stream",
            headers={"Cache-Control": "private, max-age=600", "X-Image-Proxy-Trace": trace_id},
        )
