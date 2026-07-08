from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from .runtime_settings import _DEFAULT_MEDIA_PROXY_SUFFIXES, normalize_media_proxy_suffixes

_MEDIA_PROXY_TTL_SECONDS = 10 * 60
_ALLOWED_IMAGE_HOST = "designerapp.officeapps.live.com"
_ALLOWED_IMAGE_PATH = "/designerapp/document.ashx"
_ALLOWED_ASYNCGW_HOST_RE = re.compile(r"(?:^|\.)asyncgw\.teams\.microsoft\.com$", re.IGNORECASE)
_DESIGNER_URL_RE = re.compile(r"https://designerapp\.officeapps\.live\.com/designerapp/document\.ashx[^\s`)]+")
_RAW_IMAGE_RE = re.compile(
    r"!\s*`((?:https://designerapp\.officeapps\.live\.com/designerapp/document\.ashx|https?://[^`\s]+/v1/m365-media\?|/v1/m365-media\?)[^`]+)`"
)
_RAW_ASYNCGW_MEDIA_RE = re.compile(r"`(https://[^`\s]+\.asyncgw\.teams\.microsoft\.com/v1/objects/[^`\s]+/views/original/[^`\s]+)`", re.IGNORECASE)
_MARKDOWN_DESIGNER_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((https://designerapp\.officeapps\.live\.com/designerapp/document\.ashx[^)]+)\)")
_MARKDOWN_ASYNCGW_MEDIA_RE = re.compile(r"(?<!!)\[([^\]]*)\]\((https://[^)\s]+\.asyncgw\.teams\.microsoft\.com/v1/objects/[^)\s]+/views/original/[^)\s]+)\)", re.IGNORECASE)
_PLAIN_ASYNCGW_MEDIA_RE = re.compile(r"(?<!\]\()https://[^\s`)]+\.asyncgw\.teams\.microsoft\.com/v1/objects/[^\s`)]+/views/original/[^\s`)]+", re.IGNORECASE)


def _payload(account_id: str, expires_at: int, source_url: str) -> bytes:
    return f"{account_id}\n{expires_at}\n{source_url}".encode("utf-8")


def _sign(account_id: str, expires_at: int, source_url: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), _payload(account_id, expires_at, source_url), hashlib.sha256).hexdigest()


def _encode_url(source_url: str) -> str:
    return base64.urlsafe_b64encode(source_url.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_url(encoded_url: str) -> str:
    padding = "=" * (-len(encoded_url) % 4)
    return base64.urlsafe_b64decode((encoded_url + padding).encode("ascii")).decode("utf-8")


def _media_suffixes(allowed_suffixes: list[str] | None = None) -> set[str]:
    suffixes = normalize_media_proxy_suffixes(allowed_suffixes) if allowed_suffixes is not None else list(_DEFAULT_MEDIA_PROXY_SUFFIXES)
    return set(suffixes or _DEFAULT_MEDIA_PROXY_SUFFIXES)


def _filename_matches_suffixes(filename: str, suffixes: set[str]) -> bool:
    name = filename.lower().lstrip(".")
    return any(name == suffix or name.endswith("." + suffix) for suffix in suffixes)


def is_allowed_m365_media_url(source_url: str, allowed_suffixes: list[str] | None = None) -> bool:
    parsed = urlsplit(source_url)
    if parsed.scheme != "https":
        return False
    if parsed.netloc == _ALLOWED_IMAGE_HOST and parsed.path == _ALLOWED_IMAGE_PATH:
        return True
    host = parsed.hostname or ""
    if not _ALLOWED_ASYNCGW_HOST_RE.search(host):
        return False
    path = unquote(parsed.path)
    prefix = "/v1/objects/"
    marker = "/views/original/"
    if not path.startswith(prefix) or marker not in path:
        return False
    filename = path.rsplit("/", 1)[-1]
    return _filename_matches_suffixes(filename, _media_suffixes(allowed_suffixes))


def make_signed_media_proxy_url(
    base_url: str,
    account_id: str,
    source_url: str,
    secret: str,
    *,
    expires_at: int | None = None,
) -> str:
    expires = int(expires_at if expires_at is not None else time.time() + _MEDIA_PROXY_TTL_SECONDS)
    signature = _sign(account_id, expires, source_url, secret)
    query = urlencode({"account_id": account_id, "u": _encode_url(source_url), "exp": str(expires), "sig": signature})
    return f"{base_url.rstrip('/')}/v1/m365-media?{query}"


def verify_signed_media_proxy_params(
    account_id: str,
    encoded_url: str,
    expires_at: str,
    signature: str,
    secret: str,
    *,
    now: float | None = None,
) -> str | None:
    try:
        expires = int(expires_at)
        source_url = _decode_url(encoded_url)
    except Exception:
        return None
    if expires < int(now if now is not None else time.time()):
        return None
    expected = _sign(account_id, expires, source_url, secret)
    if not hmac.compare_digest(expected, signature):
        return None
    return source_url


def _media_filename(source_url: str) -> str:
    name = unquote(urlsplit(source_url).path.rstrip("/").rsplit("/", 1)[-1])
    return name or "media"


def content_disposition_for_media(source_url: str) -> str:
    """Build a Content-Disposition header for the media download.

    Uses the model-supplied display filename (e.g. ``rain_sound.wav``), which is
    stripped before the upstream asyncgw fetch but still gives the browser a
    sensible download name and extension. Non-ASCII names get an RFC 5987
    ``filename*`` value plus an ASCII-safe ``filename`` fallback.
    """
    filename = _media_filename(source_url)
    ascii_name = filename.encode("ascii", "ignore").decode("ascii").replace('"', "")
    fallback = ascii_name or "media"
    disposition = f'attachment; filename="{fallback}"'
    if ascii_name != filename:
        disposition += f"; filename*=UTF-8''{quote(filename)}"
    return disposition


def asyncgw_object_fetch_url(source_url: str) -> str:
    """Return the real fetchable asyncgw object URL.

    The model appends a display filename after ``/views/original/`` (e.g.
    ``bird_chirp.wav``) that is NOT part of the real object path; asyncgw serves
    the object at the bare ``/v1/objects/<id>/views/original`` and returns 404
    when the extra filename segment is present. Strip that trailing segment for
    asyncgw hosts only; all other URLs (designer images, already-bare objects)
    are returned unchanged.
    """
    parsed = urlsplit(source_url)
    host = parsed.hostname or ""
    if not _ALLOWED_ASYNCGW_HOST_RE.search(host):
        return source_url
    marker = "/views/original"
    idx = parsed.path.find(marker)
    if idx < 0:
        return source_url
    trimmed_path = parsed.path[: idx + len(marker)]
    if trimmed_path == parsed.path:
        return source_url
    return f"{parsed.scheme}://{parsed.netloc}{trimmed_path}"


def designer_object_fetch_url(source_url: str) -> str:
    """Return the real fetchable designer image URL.

    The browser loads designer images WITHOUT the ``fileToken`` query param, using
    a designer-scoped Authorization token instead. The model-supplied ``fileToken``
    has the wrong audience and makes the server reject the request with HTTP 401,
    so drop it before fetching while keeping every other query param intact. Only
    officeapps.live.com hosts are touched; all other URLs are returned unchanged.
    """
    parsed = urlsplit(source_url)
    host = (parsed.hostname or "").lower()
    if host != _ALLOWED_IMAGE_HOST and not host.endswith(".officeapps.live.com"):
        return source_url
    kept = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() != "filetoken"]
    new_query = urlencode(kept)
    if new_query == parsed.query:
        return source_url
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return f"{base}?{new_query}" if new_query else base


def designer_file_token(source_url: str) -> str:
    """Return the RAW fileToken value from a designer image URL.

    The browser moves the ``fileToken`` out of the query string and into a
    dedicated ``FileToken`` request header. Return its value byte-for-byte (no
    URL-decoding) so the base64url token is replayed exactly as supplied. Only
    officeapps.live.com hosts are considered; other URLs return an empty string.
    """
    parsed = urlsplit(source_url)
    host = (parsed.hostname or "").lower()
    if host != _ALLOWED_IMAGE_HOST and not host.endswith(".officeapps.live.com"):
        return ""
    for pair in parsed.query.split("&"):
        key, sep, value = pair.partition("=")
        if sep and key.lower() == "filetoken":
            return value
    return ""


def normalize_m365_media_text(text: str) -> str:
    def raw_repl(match: re.Match[str]) -> str:
        return f"![image]({match.group(1).strip()})"

    def raw_media_repl(match: re.Match[str]) -> str:
        source_url = match.group(1).strip()
        return f"[下载 {_media_filename(source_url)}]({source_url})"

    normalized = _RAW_ASYNCGW_MEDIA_RE.sub(raw_media_repl, _RAW_IMAGE_RE.sub(raw_repl, text))
    stripped = normalized.strip()
    if stripped.startswith("!") and "`" not in stripped:
        direct = _DESIGNER_URL_RE.search(stripped)
        if direct and stripped in {f"! {direct.group(0)}", f"!{direct.group(0)}"}:
            return f"![image]({direct.group(0)})"
    return normalized.strip() if normalized != text else text


def rewrite_m365_media_urls(
    text: str,
    *,
    base_url: str,
    account_id: str | None,
    secret: str,
    now: float | None = None,
    allowed_suffixes: list[str] | None = None,
) -> str:
    if not account_id or not secret:
        return normalize_m365_media_text(text)
    normalized = normalize_m365_media_text(text)
    expires_at = int((now if now is not None else time.time()) + _MEDIA_PROXY_TTL_SECONDS)

    def md_repl(match: re.Match[str]) -> str:
        alt = match.group(1) or "image"
        source_url = match.group(2).strip()
        if not is_allowed_m365_media_url(source_url, allowed_suffixes):
            return match.group(0)
        proxy_url = make_signed_media_proxy_url(base_url, account_id, source_url, secret, expires_at=expires_at)
        return f"![{alt}]({proxy_url})"

    def media_repl(match: re.Match[str]) -> str:
        label = match.group(1) or f"下载 {_media_filename(match.group(2))}"
        source_url = match.group(2).strip()
        if not is_allowed_m365_media_url(source_url, allowed_suffixes):
            return match.group(0)
        proxy_url = make_signed_media_proxy_url(base_url, account_id, source_url, secret, expires_at=expires_at)
        return f"[{label}]({proxy_url})"

    def plain_media_repl(match: re.Match[str]) -> str:
        source_url = match.group(0).strip()
        if not is_allowed_m365_media_url(source_url, allowed_suffixes):
            return match.group(0)
        return make_signed_media_proxy_url(base_url, account_id, source_url, secret, expires_at=expires_at)

    rewritten = _MARKDOWN_ASYNCGW_MEDIA_RE.sub(media_repl, _MARKDOWN_DESIGNER_IMAGE_RE.sub(md_repl, normalized))
    return _PLAIN_ASYNCGW_MEDIA_RE.sub(plain_media_repl, rewritten)
