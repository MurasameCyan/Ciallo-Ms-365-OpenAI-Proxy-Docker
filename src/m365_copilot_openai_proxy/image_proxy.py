from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from urllib.parse import urlencode, urlsplit

_IMAGE_PROXY_TTL_SECONDS = 10 * 60
_ALLOWED_IMAGE_HOST = "designerapp.officeapps.live.com"
_ALLOWED_IMAGE_PATH = "/designerapp/document.ashx"
_DESIGNER_URL_RE = re.compile(r"https://designerapp\.officeapps\.live\.com/designerapp/document\.ashx[^\s`)]+")
_RAW_DESIGNER_IMAGE_RE = re.compile(r"!\s*`(https://designerapp\.officeapps\.live\.com/designerapp/document\.ashx[^`]+)`")
_MARKDOWN_DESIGNER_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((https://designerapp\.officeapps\.live\.com/designerapp/document\.ashx[^)]+)\)")


def _payload(account_id: str, expires_at: int, source_url: str) -> bytes:
    return f"{account_id}\n{expires_at}\n{source_url}".encode("utf-8")


def _sign(account_id: str, expires_at: int, source_url: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), _payload(account_id, expires_at, source_url), hashlib.sha256).hexdigest()


def _encode_url(source_url: str) -> str:
    return base64.urlsafe_b64encode(source_url.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_url(encoded_url: str) -> str:
    padding = "=" * (-len(encoded_url) % 4)
    return base64.urlsafe_b64decode((encoded_url + padding).encode("ascii")).decode("utf-8")


def is_allowed_m365_image_url(source_url: str) -> bool:
    parsed = urlsplit(source_url)
    return parsed.scheme == "https" and parsed.netloc == _ALLOWED_IMAGE_HOST and parsed.path == _ALLOWED_IMAGE_PATH


def make_signed_image_proxy_url(
    base_url: str,
    account_id: str,
    source_url: str,
    secret: str,
    *,
    expires_at: int | None = None,
) -> str:
    expires = int(expires_at if expires_at is not None else time.time() + _IMAGE_PROXY_TTL_SECONDS)
    signature = _sign(account_id, expires, source_url, secret)
    query = urlencode({"account_id": account_id, "u": _encode_url(source_url), "exp": str(expires), "sig": signature})
    return f"{base_url.rstrip('/')}/v1/m365-image?{query}"


def verify_signed_image_proxy_params(
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


def normalize_m365_image_text(text: str) -> str:
    def raw_repl(match: re.Match[str]) -> str:
        return f"![image]({match.group(1).strip()})"

    normalized = _RAW_DESIGNER_IMAGE_RE.sub(raw_repl, text)
    stripped = normalized.strip()
    if stripped.startswith("!") and "`" not in stripped:
        direct = _DESIGNER_URL_RE.search(stripped)
        if direct and stripped in {f"! {direct.group(0)}", f"!{direct.group(0)}"}:
            return f"![image]({direct.group(0)})"
    return normalized.strip() if normalized != text else text


def rewrite_m365_image_urls(
    text: str,
    *,
    base_url: str,
    account_id: str | None,
    secret: str,
    now: float | None = None,
) -> str:
    if not account_id or not secret:
        return normalize_m365_image_text(text)
    normalized = normalize_m365_image_text(text)
    expires_at = int((now if now is not None else time.time()) + _IMAGE_PROXY_TTL_SECONDS)

    def md_repl(match: re.Match[str]) -> str:
        alt = match.group(1) or "image"
        source_url = match.group(2).strip()
        if not is_allowed_m365_image_url(source_url):
            return match.group(0)
        proxy_url = make_signed_image_proxy_url(base_url, account_id, source_url, secret, expires_at=expires_at)
        return f"![{alt}]({proxy_url})"

    return _MARKDOWN_DESIGNER_IMAGE_RE.sub(md_repl, normalized)
