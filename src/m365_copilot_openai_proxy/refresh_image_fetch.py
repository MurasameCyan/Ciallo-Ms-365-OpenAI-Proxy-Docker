from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from .media_proxy import designer_object_fetch_url
from .refresh_chromium import chromium_proxy_args
from .refresh_cookies import _cdp_cookie_params
from .refresh_media import (
    UpstreamMediaNotFound,
    _auth_headers_for_account,
    _body_preview,
    _designer_fetch_expression,
    _is_designer_media_url,
)

# Media (and future video) bodies are returned base64-encoded over the CDP
# WebSocket and can far exceed the websockets 1 MB default frame limit (a 2 MB
# image already triggers HTTP 1009 "message too big"). Media sizes are
# unpredictable, so disable the frame cap for the media-fetch socket only; the
# upstream is the trusted M365 endpoint.
_CDP_MEDIA_MAX_MESSAGE_BYTES = None  # None = no size limit


async def fetch_image_one(
    accounts,
    profile_root,
    account_id: str,
    url: str,
    *,
    event_sink=None,
    chromium_path,
    cleanup_profile_locks,
    close_chromium_gracefully,
    launch_timeout_seconds,
) -> tuple[bytes, str]:
    account = accounts.get(account_id)
    if account is None:
        raise RuntimeError(f"account {account_id} not found")
    account_profile_dir = profile_root / account_id
    if not account_profile_dir.exists():
        raise RuntimeError("account browser profile is missing; push cookies again")
    profile_root.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(tempfile.mkdtemp(prefix=f"{account_id}-media-", dir=profile_root))
    cleanup_profile_locks(profile_dir)
    proc = None
    try:
        chrome_bin = chromium_path()
        cdp_port = account.cdp_port
        if event_sink:
            event_sink("chromium_launch", cdp_port=cdp_port, browser=chrome_bin)
        proc = subprocess.Popen([
            chrome_bin,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={profile_dir}",
            *chromium_proxy_args(),
            "--no-first-run",
            "--no-default-browser-check",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-breakpad",
            "--disable-extensions",
            "--disable-software-rasterizer",
            "--headless=new",
            "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import httpx
        import websockets

        deadline = time.time() + launch_timeout_seconds
        tab = None
        while time.time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=2) as client:
                    tabs = (await client.get(f"http://localhost:{cdp_port}/json/list")).json()
                tab = next((t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
                if tab:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.3)
        if not tab:
            if event_sink:
                event_sink("chromium_cdp_timeout", cdp_port=cdp_port)
            raise RuntimeError("Chromium CDP tab did not become ready")
        if event_sink:
            event_sink("chromium_cdp_ready", cdp_port=cdp_port)

        async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=_CDP_MEDIA_MAX_MESSAGE_BYTES) as ws:
            next_id = 1

            async def cdp_call(method: str, params: dict | None = None) -> dict:
                nonlocal next_id
                msg_id = next_id
                next_id += 1
                payload = {"id": msg_id, "method": method}
                if params is not None:
                    payload["params"] = params
                await ws.send(json.dumps(payload))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == msg_id:
                        return msg

            await cdp_call("Network.enable")
            injected_cookies = 0
            now = time.time()
            for cookie in account.cookies:
                domain = str(cookie.get("domain", "") or ".microsoft.com")
                domain_l = domain.lower()
                if not any(d in domain_l for d in ("microsoft", "office.com", "live.com")):
                    continue
                try:
                    params, _, _ = _cdp_cookie_params(cookie, now)
                except (TypeError, ValueError):
                    continue
                result = await cdp_call("Network.setCookie", params)
                if result.get("result", {}).get("success"):
                    injected_cookies += 1
            if event_sink:
                event_sink("chromium_cookies", cookie_count=injected_cookies)
            # Auth is derived from the URL that still carries the fileToken so it
            # can be lifted into the FileToken header; the request itself must use
            # the stripped URL, or designerapp rejects it.
            auth_headers, auth_source = _auth_headers_for_account(account, url)
            if _is_designer_media_url(url):
                # A top-level document navigation to document.ashx is rejected
                # with HTTP 400 (Sec-Fetch-Dest: document); the M365 page loads
                # the image with an in-page fetch (Sec-Fetch-Dest: empty). Load
                # the designerapp origin first so the fetch is same-origin, then
                # replay the browser's request verbatim (Authorization + FileToken
                # headers, fileToken stripped from the query, cookies included).
                fetch_target = designer_object_fetch_url(url)
                if event_sink and fetch_target != url:
                    event_sink("designer_url_normalized", original_query=urlsplit(url).query, fetch_query=urlsplit(fetch_target).query)
                parsed_target = urlsplit(fetch_target)
                origin = f"{parsed_target.scheme}://{parsed_target.netloc}/"
                await cdp_call("Page.enable")
                await cdp_call("Runtime.enable")
                await cdp_call("Page.navigate", {"url": origin})
                if event_sink:
                    event_sink("chromium_fetch_start", token_header=bool(auth_headers), auth_source=auth_source)
                eval_result = await cdp_call(
                    "Runtime.evaluate",
                    {
                        "expression": _designer_fetch_expression(fetch_target, auth_headers),
                        "awaitPromise": True,
                        "returnByValue": True,
                    },
                )
                result_obj = eval_result.get("result") or {}
                if result_obj.get("exceptionDetails"):
                    raise RuntimeError(str(result_obj.get("exceptionDetails")))
                value = (result_obj.get("result") or {}).get("value") or {}
                if not value.get("ok"):
                    raise RuntimeError(str(value.get("error") or "designer fetch failed in Chromium"))
                status = int(value.get("status") or 0)
                content_type = str(value.get("contentType") or "application/octet-stream")
                decoded = base64.b64decode(str(value.get("body") or ""))
                if event_sink:
                    event_sink(
                        "chromium_response",
                        status_code=status,
                        content_type=content_type,
                        response_host=parsed_target.hostname or "",
                        response_path=parsed_target.path,
                        www_authenticate="",
                    )
                    event_sink("chromium_body", bytes=len(decoded), base64_encoded=True, body_preview=_body_preview(decoded) if status >= 400 else "")
                if status == 404:
                    raise UpstreamMediaNotFound("upstream media returned HTTP 404")
                if status >= 400:
                    raise RuntimeError(f"upstream media returned HTTP {status}")
                return decoded, content_type
            nav_url = url
            if auth_headers:
                await cdp_call("Network.setExtraHTTPHeaders", {"headers": auth_headers})
            await cdp_call("Page.enable")
            if event_sink:
                event_sink("chromium_navigate", token_header=bool(auth_headers), auth_source=auth_source)
            navigate_id = next_id
            next_id += 1
            await ws.send(json.dumps({"id": navigate_id, "method": "Page.navigate", "params": {"url": nav_url}}))
            request_id = ""
            content_type = "application/octet-stream"
            status = 0
            deadline = time.time() + 25
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
                except asyncio.TimeoutError:
                    break
                msg = json.loads(raw)
                method = msg.get("method")
                params = msg.get("params") or {}
                if method == "Network.responseReceived":
                    response = params.get("response") or {}
                    response_url = str(response.get("url") or "")
                    if response_url == nav_url or response_url.startswith("https://designerapp.officeapps.live.com/designerapp/document.ashx"):
                        request_id = str(params.get("requestId") or "")
                        status = int(response.get("status") or 0)
                        content_type = str(response.get("mimeType") or "application/octet-stream")
                        response_headers = response.get("headers") or {}
                        if event_sink:
                            event_sink(
                                "chromium_response",
                                status_code=status,
                                content_type=content_type,
                                response_host=urlsplit(response_url).hostname or "",
                                response_path=urlsplit(response_url).path,
                                www_authenticate=str(response_headers.get("www-authenticate") or response_headers.get("WWW-Authenticate") or ""),
                            )
                elif method == "Network.loadingFinished" and request_id and params.get("requestId") == request_id:
                    break
                elif method == "Network.loadingFailed" and request_id and params.get("requestId") == request_id:
                    raise RuntimeError(str(params.get("errorText") or "image loading failed"))
            if not request_id:
                raise RuntimeError("image response was not observed in Chromium")
            body_response = await cdp_call("Network.getResponseBody", {"requestId": request_id})
            result = body_response.get("result") or {}
            body = str(result.get("body") or "")
            if result.get("base64Encoded"):
                decoded = base64.b64decode(body)
                if event_sink:
                    event_sink("chromium_body", bytes=len(decoded), base64_encoded=True, body_preview=_body_preview(decoded) if status >= 400 else "")
                if status == 404:
                    raise UpstreamMediaNotFound("upstream media returned HTTP 404")
                if status >= 400:
                    raise RuntimeError(f"upstream media returned HTTP {status}")
                return decoded, content_type
            encoded = body.encode("utf-8")
            if event_sink:
                event_sink("chromium_body", bytes=len(encoded), base64_encoded=False, body_preview=_body_preview(encoded) if status >= 400 else "")
            if status == 404:
                raise UpstreamMediaNotFound("upstream media returned HTTP 404")
            if status >= 400:
                raise RuntimeError(f"upstream media returned HTTP {status}")
            return encoded, content_type
    finally:
        await close_chromium_gracefully(account.cdp_port, proc)
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        shutil.rmtree(profile_dir, ignore_errors=True)
