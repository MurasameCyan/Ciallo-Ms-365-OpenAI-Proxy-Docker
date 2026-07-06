from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from .image_proxy import (
    is_allowed_m365_image_url,
    make_signed_image_proxy_url,
    rewrite_m365_image_urls,
    verify_signed_image_proxy_params,
)


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
        secret = str(getattr(app.state, "image_proxy_secret", "") or "")
        source_url = verify_signed_image_proxy_params(account_id, u, exp, sig, secret)
        if source_url is None:
            raise HTTPException(status_code=403, detail="Invalid image proxy signature")
        if not is_allowed_m365_image_url(source_url):
            raise HTTPException(status_code=400, detail="Unsupported image host")
        account = app.state.account_store.get(account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        fetcher = getattr(app.state.refresh_scheduler, "fetch_image", None)
        if fetcher is None:
            raise HTTPException(status_code=503, detail="Image fetcher is unavailable")
        try:
            content, content_type = await fetcher(account_id, source_url)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Image fetch failed: {exc}") from exc
        return Response(
            content=content,
            media_type=content_type or "application/octet-stream",
            headers={"Cache-Control": "private, max-age=600"},
        )
