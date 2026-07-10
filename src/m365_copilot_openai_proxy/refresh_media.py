from __future__ import annotations

import json
from urllib.parse import urlsplit

from .media_proxy import designer_file_token

def _auth_headers_for_token(token: str) -> dict[str, str]:
    token = token.strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _is_teams_media_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "teams.microsoft.com" or host.endswith(".teams.microsoft.com")


def _is_designer_media_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "designerapp.officeapps.live.com" or host.endswith(".officeapps.live.com")


def _designer_fetch_expression(url: str, headers: dict[str, str]) -> str:
    """Build a JS expression that replays the browser's designer image fetch.

    designerapp rejects both plain httpx GETs and top-level document navigations
    (HTTP 400); the M365 page loads the image with an in-page ``fetch`` whose
    ``Sec-Fetch-Dest`` is ``empty``. Running the same fetch inside Chromium (from
    the designerapp origin) reproduces that exact request shape, including the
    Authorization + FileToken headers and same-origin cookies. The body is
    returned base64-encoded so binary image bytes survive the CDP round trip.
    """
    url_literal = json.dumps(url)
    headers_literal = json.dumps(headers or {})
    return (
        "(async () => {"
        "  try {"
        f"    const r = await fetch({url_literal}, {{headers: {headers_literal}, credentials: 'include'}});"
        "    const buf = await r.arrayBuffer();"
        "    const bytes = new Uint8Array(buf);"
        "    let bin = '';"
        "    const chunk = 0x8000;"
        "    for (let i = 0; i < bytes.length; i += chunk) {"
        "      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));"
        "    }"
        "    return {ok: true, status: r.status, contentType: r.headers.get('content-type') || '', body: btoa(bin)};"
        "  } catch (e) { return {ok: false, error: String(e)}; }"
        "})()"
    )


def _auth_headers_for_account(account, url: str) -> tuple[dict[str, str], str]:
    media_token = str(getattr(account, "media_auth_token", "") or "").strip()
    if media_token and _is_teams_media_url(url):
        return _auth_headers_for_token(media_token), "media"
    if _is_designer_media_url(url):
        # designerapp uses a dedicated Authorization token (a raw JWE) that the
        # browser sends WITHOUT a "Bearer " prefix; replay it verbatim. It also
        # moves the fileToken out of the query string into a FileToken request
        # header, so extract and replay that too. The substrate account token has
        # the wrong audience (HTTP 401), so only fall back to cookies-only when we
        # have not captured the designer token yet.
        headers: dict[str, str] = {}
        file_token = designer_file_token(url)
        if file_token:
            headers["FileToken"] = file_token
        designer_token = str(getattr(account, "designer_auth_token", "") or "").strip()
        if designer_token:
            headers["Authorization"] = designer_token
            return headers, "designer"
        return headers, "designer_cookie"
    if account.token:
        return _auth_headers_for_token(account.token), "account"
    return {}, ""


class UpstreamMediaNotFound(RuntimeError):
    pass


def _body_preview(content: bytes, limit: int = 300) -> str:
    return content[:limit].decode("utf-8", errors="replace")


