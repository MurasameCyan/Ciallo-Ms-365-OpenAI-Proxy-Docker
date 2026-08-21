from __future__ import annotations

import re
import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request

from .call_log_store import append_call_log, record_response_text
from .config import Settings
from .routes_api_common import apply_request_model, request_model_alias, upstream_http_error
from .routes_media_proxy import request_media_rewriter
from .media_proxy import is_allowed_m365_media_url, verify_signed_media_proxy_params
from .substrate_client import SubstrateCopilotError
from .usage_store import estimate_upstream_input_tokens


_IMAGE_URL = re.compile(
    r"https://designerapp\.officeapps\.live\.com/designerapp/document\.ashx[^\s)]+",
    re.IGNORECASE,
)
_GLOBAL_MEDIA_ACCOUNT_ID = "__global__"


def _image_url_from_text(text: object) -> str:
    match = _IMAGE_URL.search(str(text or ""))
    if not match:
        return ""
    # Markdown and prose often leave sentence punctuation immediately after the
    # query string. It is not part of the signed source URL.
    return match.group(0).rstrip(".,;:!?]} )`\\\"")


def _safe_image_record_text(text: object) -> str:
    """Keep bearer-like Designer URLs out of the persistent call log."""
    redacted = _IMAGE_URL.sub("[generated image]", str(text or ""))
    return re.sub(
        r"fileToken=[^&\s)]+",
        "fileToken=[redacted]",
        redacted,
        flags=re.IGNORECASE,
    )


def _signed_proxy_url_for_request(
    app: FastAPI, request: Request, value: object, expected_source_url: str
) -> bool:
    """Accept only a locally minted, signed media URL.

    The image endpoint must never fall back to returning Designer's source URL,
    which contains a bearer-like ``fileToken`` query value.
    """
    parsed = urlsplit(str(value or ""))
    base = urlsplit(str(request.base_url))
    if parsed.scheme not in {"http", "https"} or parsed.netloc != base.netloc:
        return False
    if parsed.path != "/v1/m365-media":
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(len(query.get(key, [])) != 1 for key in ("account_id", "u", "exp", "sig")):
        return False
    account = getattr(request.state, "account", None)
    account_id = getattr(account, "id", None)
    if account_id is None and getattr(app.state, "token_store", None) is not None:
        if app.state.token_store.get():
            account_id = _GLOBAL_MEDIA_ACCOUNT_ID
    if not account_id:
        return False
    secret = str(getattr(app.state, "media_proxy_secret", "") or "")
    source_url = verify_signed_media_proxy_params(
        query["account_id"][0], query["u"][0], query["exp"][0], query["sig"][0], secret
    )
    return bool(
        query["account_id"][0] == account_id
        and source_url
        and source_url == expected_source_url
        and is_allowed_m365_media_url(source_url)
    )


def register_image_routes(
    app: FastAPI,
    get_settings: Callable[[], Settings],
    get_copilot_client: Callable[..., object],
) -> None:
    @app.post("/v1/images/generations")
    async def image_generations(
        raw_request: Request,
        settings: Settings = Depends(get_settings),
    ) -> dict:
        try:
            body = await raw_request.json()
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Image request must be an object.")
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required.")
        raw_n = body.get("n", 1)
        if isinstance(raw_n, bool) or not isinstance(raw_n, int):
            raise HTTPException(status_code=400, detail="n must be an integer.")
        if raw_n != 1:
            raise HTTPException(status_code=400, detail="Only n=1 is supported.")
        if str(body.get("response_format") or "url") != "url":
            raise HTTPException(status_code=400, detail="Only response_format=url is supported.")
        size = str(body.get("size") or "1024x1024")
        # The upstream prompt path does not guarantee pixel dimensions. Advertise
        # only the one size tested end-to-end; this is still best effort.
        if size != "1024x1024":
            raise HTTPException(
                status_code=400,
                detail="Only size=1024x1024 is supported (best effort).",
            )

        requested_model = str(body.get("model") or request_model_alias(app, raw_request, settings))
        try:
            client, tone, is_consumer = apply_request_model(
                app, raw_request, get_copilot_client, requested_model
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if is_consumer:
            raise HTTPException(
                status_code=400,
                detail="Image generations are only supported for M365 accounts.",
            )
        translated_prompt = (
            "Generate exactly one image. Do not describe it without producing the image. "
            f"Requested size: {size}. Prompt: {prompt}"
        )
        record = {
            "api": "images",
            "endpoint": "/v1/images/generations",
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "stream": False,
            "tools": [],
            "tool_choice": "none",
            "messages": 1,
            "model": requested_model,
            "tone": tone,
            "tool_planning": "none",
            "image_size": size,
            "image_n": raw_n,
            "usage_input_tokens": estimate_upstream_input_tokens(translated_prompt),
            "tool_calls_result": [],
        }
        try:
            text = await client.chat(translated_prompt, [], None, None)
        except SubstrateCopilotError as exc:
            record["error"] = str(exc)
            record_response_text(app.state, record, "")
            append_call_log(app.state, record)
            raise upstream_http_error(exc) from exc
        except HTTPException:
            raise
        except Exception as exc:
            record["error"] = str(exc)
            record_response_text(app.state, record, "")
            append_call_log(app.state, record)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        source_url = _image_url_from_text(text)
        if not source_url:
            record["error"] = "no_generated_image"
            record_response_text(app.state, record, _safe_image_record_text(text))
            append_call_log(app.state, record)
            raise HTTPException(status_code=502, detail="Upstream returned no generated image.")
        try:
            rewrite = request_media_rewriter(app, raw_request)
            rewritten = rewrite(f"![image]({source_url})")
        except Exception as exc:
            record["error"] = "media_rewrite_failed"
            record_response_text(app.state, record, _safe_image_record_text(text))
            append_call_log(app.state, record)
            raise HTTPException(status_code=502, detail="Generated image URL could not be secured.") from exc
        url_match = re.search(r"\((https?://[^)]+)\)", rewritten)
        if not url_match or not _signed_proxy_url_for_request(
            app, raw_request, url_match.group(1), source_url
        ):
            record["error"] = "unsecured_generated_image_url"
            record_response_text(app.state, record, _safe_image_record_text(text))
            append_call_log(app.state, record)
            raise HTTPException(status_code=502, detail="Generated image URL could not be secured.")
        record_response_text(app.state, record, _safe_image_record_text(text))
        append_call_log(app.state, record)
        return {
            "created": int(time.time()),
            "data": [{"url": url_match.group(1), "revised_prompt": prompt}],
            "model": requested_model,
        }
