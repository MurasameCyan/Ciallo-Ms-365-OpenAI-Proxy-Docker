from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

# Session cookies without an absolute expiry are given this floor so Chromium
# does not drop them immediately after inject. Keep in sync with callers in
# refresh_scheduler that also use this floor for account cookie_expires_at.
_SESSION_COOKIE_PERSIST_SECONDS = 12 * 60 * 60

_CRITICAL_AUTH_COOKIE_PREFIXES = (
    "ESTSAUTH", "SignInStateCookie", "ESTSSC", "buid", "esctx",
    "x-ms-gateway-slice", "stsservicecookie", "CCState", "wlidperf",
)

def _critical_cookie_report(cookies: list[dict]) -> list[str]:
    """Summarise which critical MS auth cookies are present in the pushed set."""
    report: list[str] = []
    for c in cookies:
        name = str(c.get("name", "") or "")
        if not any(name.upper().startswith(p.upper()) for p in _CRITICAL_AUTH_COOKIE_PREFIXES):
            continue
        exp_raw = c.get("expires") or c.get("expirationDate")
        report.append(
            f"{name}@{c.get('domain', '')}"
            f"(httpOnly={bool(c.get('httpOnly'))},session={not bool(exp_raw)})"
        )
    return report


def _cookie_header_for_url(cookies: list[dict], url: str) -> str:
    host = urlsplit(url).hostname or ""
    now = time.time()
    pairs: list[str] = []
    for cookie in cookies:
        name = str(cookie.get("name") or "")
        value = str(cookie.get("value") or "")
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        expires = cookie.get("expirationDate") or cookie.get("expires") or 0
        try:
            if expires and _normalize_cookie_expires(expires) < now:
                continue
        except (TypeError, ValueError):
            pass
        if not name or not value:
            continue
        if domain and host != domain and not host.endswith("." + domain):
            continue
        pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _cookie_names_for_url(cookies: list[dict[str, Any]], url: str) -> list[str]:
    host = urlsplit(url).hostname or ""
    names: list[str] = []
    for cookie in cookies:
        name = str(cookie.get("name") or "").strip()
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        if name and domain and (host == domain or host.endswith("." + domain)):
            names.append(name)
    return names


def _normalize_cookie_expires(value: object) -> float:
    expires = float(value)
    if expires > 10_000_000_000:
        expires = expires / 1000
    return expires


def _normalize_cookie_same_site(value: object) -> str | None:
    same_site = str(value or "").strip().lower().replace("-", "_")
    if same_site in ("", "unspecified", "no_restriction_unspecified"):
        return None
    if same_site in ("none", "no_restriction"):
        return "None"
    if same_site == "lax":
        return "Lax"
    if same_site == "strict":
        return "Strict"
    return None


def _cdp_cookie_params(cookie: dict, now: float) -> tuple[dict, float, bool]:
    name = str(cookie.get("name") or "")
    raw_value = cookie.get("value")
    if not name or raw_value is None:
        raise ValueError("cookie name and value are required")
    value = str(raw_value)
    domain = str(cookie.get("domain") or ".microsoft.com").strip()
    host = domain.lstrip(".")
    if not host:
        host = "microsoft.com"
    params = {
        "name": name,
        "value": value,
        "url": f"https://{host}/",
        "path": cookie.get("path", "/") or "/",
        "secure": bool(cookie.get("secure", True)),
        "httpOnly": bool(cookie.get("httpOnly", False)),
    }
    if name.startswith("__Host-"):
        params["path"] = "/"
        params["secure"] = True
    else:
        params["domain"] = domain
        if name.startswith("__Secure-"):
            params["secure"] = True
    same_site = _normalize_cookie_same_site(cookie.get("sameSite"))
    if same_site:
        params["sameSite"] = same_site
    if params.get("sameSite") == "None":
        params["secure"] = True
    raw_expires = cookie.get("expirationDate") or cookie.get("expires")
    if raw_expires:
        expires = _normalize_cookie_expires(raw_expires)
        params["expires"] = expires
        return params, expires, False
    expires = now + _SESSION_COOKIE_PERSIST_SECONDS
    params["expires"] = expires
    return params, expires, True


