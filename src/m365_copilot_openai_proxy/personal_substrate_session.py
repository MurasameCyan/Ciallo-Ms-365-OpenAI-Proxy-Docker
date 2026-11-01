"""Validate captured personal Substrate browser state without selecting a URL."""
from __future__ import annotations

import math
import re
import time
from urllib.parse import parse_qs, urlsplit


PERSONAL_SUBSTRATE_ORIGIN = "https://copilot.com"
MSA_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"
PERSONAL_TOKEN_HOST = "login.microsoftonline.com"
PERSONAL_TOKEN_PATHS = (f"/{MSA_TENANT}/oauth2/v2.0/token", "/consumers/oauth2/v2.0/token")
# The page's own broker refresh: these request fields are enough to redeem its
# refresh token again over plain HTTP; telemetry and one-shot values are dropped.
BROKER_FORM_KEYS = frozenset({
    "client_id", "redirect_uri", "scope", "brk_client_id", "brk_redirect_uri", "client_info", "X-AnchorMailbox",
})
BROKER_QUERY_KEYS = frozenset({"client_id", "brk_client_id", "brk_redirect_uri"})
_SUBJECT_RE = re.compile(r"^(?:home|local):[a-z0-9._-]{1,512}$")
_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_COOKIE_ROOTS = ("copilot.com", "copilot.microsoft.com", "live.com", "microsoftonline.com")
_MAX_BYTES = 2 * 1024 * 1024
_MAX_STRING = 128 * 1024
_ERROR_CODES = frozenset({
    "session_expired", "identity_mismatch", "issuance_unavailable",
    "browser_unavailable", "refresh_failed",
})


class PersonalSubstrateSessionError(ValueError):
    """Malformed capture material; safe for a public 400 response."""


class PersonalSubstrateSubjectMismatch(PersonalSubstrateSessionError):
    """A valid capture subject does not match the token's pinned subject."""


def normalize_personal_substrate_error(value: object) -> str:
    return value if isinstance(value, str) and value in _ERROR_CODES else ""


def normalize_personal_substrate_expiry(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PersonalSubstrateSessionError("Personal Substrate expiry must be a Unix timestamp")
    if not 0 <= value <= 253402300799 or not math.isfinite(value):
        raise PersonalSubstrateSessionError("Personal Substrate expiry is out of range")
    return float(value)


def _allowed_domain(domain: str) -> bool:
    return any(domain == root or domain.endswith("." + root) for root in _COOKIE_ROOTS)


def normalize_personal_substrate_session(value: object, account_id: str) -> dict:
    """Return a detached, bounded capture or reject it before a credential write.

    Cookie domains outside Microsoft's personal-session roots are omitted. All
    supported browser replay attributes are retained, never turned into URLs to
    navigate to. At least one live, nonempty Microsoft cookie is required.
    """
    if not isinstance(value, dict):
        raise PersonalSubstrateSessionError("Personal Substrate session must be an object")
    if value.get("origin") != PERSONAL_SUBSTRATE_ORIGIN:
        raise PersonalSubstrateSessionError("Personal Substrate origin must be https://copilot.com")
    subject = value.get("account_id")
    if not isinstance(subject, str) or not _SUBJECT_RE.fullmatch(subject):
        raise PersonalSubstrateSessionError("Personal Substrate session identity is malformed")
    if not account_id or subject != account_id:
        raise PersonalSubstrateSubjectMismatch("Personal Substrate session must match the captured Microsoft account identity")
    if set(value) - {"origin", "account_id", "cookies", "local_storage", "session_storage", "broker"}:
        raise PersonalSubstrateSessionError("Personal Substrate session has unsupported fields")
    total = 0

    def bounded_string(item: object, maximum: int = _MAX_STRING) -> str:
        nonlocal total
        if not isinstance(item, str) or len(item) > maximum:
            raise PersonalSubstrateSessionError("Personal Substrate session string is malformed or too large")
        try:
            total += len(item.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise PersonalSubstrateSessionError("Personal Substrate session string is not valid Unicode") from exc
        if total > _MAX_BYTES:
            raise PersonalSubstrateSessionError("Personal Substrate session is too large")
        return item

    result = {"origin": PERSONAL_SUBSTRATE_ORIGIN, "account_id": subject}
    cookies = value.get("cookies")
    if not isinstance(cookies, list) or not 1 <= len(cookies) <= 512:
        raise PersonalSubstrateSessionError("Personal Substrate cookies must be a nonempty bounded list")
    normalized_cookies = []
    reusable = False
    now = time.time()
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise PersonalSubstrateSessionError("Personal Substrate cookie must be an object")
        name = bounded_string(cookie.get("name"), 4096)
        content = bounded_string(cookie.get("value"))
        domain = bounded_string(cookie.get("domain"), 254)
        host = domain.removeprefix(".")
        if not _COOKIE_NAME_RE.fullmatch(name) or domain != domain.lower() or not _DOMAIN_RE.fullmatch(host):
            raise PersonalSubstrateSessionError("Personal Substrate cookie name or domain is malformed")
        if any(ord(char) < 32 or ord(char) == 127 for char in content):
            raise PersonalSubstrateSessionError("Personal Substrate cookie value is malformed")
        normalized = {"name": name, "value": content, "domain": domain}
        if "path" in cookie:
            path = bounded_string(cookie["path"], 4096)
            if not path.startswith("/") or any(ord(char) < 32 for char in path):
                raise PersonalSubstrateSessionError("Personal Substrate cookie path is malformed")
            normalized["path"] = path
        for key in ("secure", "httpOnly", "hostOnly", "session", "sameParty", "partitioned"):
            if key in cookie:
                if not isinstance(cookie[key], bool):
                    raise PersonalSubstrateSessionError("Personal Substrate cookie flags must be booleans")
                normalized[key] = cookie[key]
        expiry_values = []
        for key in ("expires", "expirationDate"):
            if key in cookie:
                expiry = cookie[key]
                if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not -1 <= expiry <= 253402300799 or not math.isfinite(expiry):
                    raise PersonalSubstrateSessionError("Personal Substrate cookie expiry is malformed")
                normalized[key] = expiry
                if expiry > 0:
                    expiry_values.append(expiry)
        if "sameSite" in cookie:
            same_site = cookie["sameSite"]
            if same_site not in ("Strict", "Lax", "None", "strict", "lax", "no_restriction", "unspecified"):
                raise PersonalSubstrateSessionError("Personal Substrate cookie sameSite is malformed")
            normalized["sameSite"] = same_site
        for key in ("storeId", "firstPartyDomain", "sourceScheme", "priority"):
            if key in cookie:
                normalized[key] = bounded_string(cookie[key], 4096)
        for key in ("sourcePort", "size"):
            if key in cookie:
                number = cookie[key]
                if isinstance(number, bool) or not isinstance(number, int) or not -1 <= number <= 2**31 - 1:
                    raise PersonalSubstrateSessionError("Personal Substrate cookie metadata is malformed")
                normalized[key] = number
        if "partitionKey" in cookie:
            partition = cookie["partitionKey"]
            if isinstance(partition, str):
                site = bounded_string(partition, 2048)
                normalized["partitionKey"] = site
            elif isinstance(partition, dict) and not set(partition) - {"topLevelSite", "hasCrossSiteAncestor"}:
                site = bounded_string(partition.get("topLevelSite"), 2048)
                normalized["partitionKey"] = {"topLevelSite": site}
                if "hasCrossSiteAncestor" in partition:
                    if not isinstance(partition["hasCrossSiteAncestor"], bool):
                        raise PersonalSubstrateSessionError("Personal Substrate cookie partition is malformed")
                    normalized["partitionKey"]["hasCrossSiteAncestor"] = partition["hasCrossSiteAncestor"]
            else:
                raise PersonalSubstrateSessionError("Personal Substrate cookie partition is malformed")
            try:
                parsed = urlsplit(site)
                allowed = (
                    parsed.scheme == "https" and parsed.hostname
                    and _allowed_domain(parsed.hostname)
                    and not parsed.username and not parsed.password
                    and parsed.port in (None, 443) and parsed.path in ("", "/")
                    and not parsed.query and not parsed.fragment
                )
            except ValueError:
                allowed = False
            if not allowed:
                raise PersonalSubstrateSessionError("Personal Substrate cookie partition site is not allowed")
        if set(cookie) - set(normalized):
            raise PersonalSubstrateSessionError("Personal Substrate cookie has unsupported metadata")
        if _allowed_domain(host):
            normalized_cookies.append(normalized)
            reusable = reusable or bool(content and (not expiry_values or min(expiry_values) > now))
    if not reusable:
        raise PersonalSubstrateSessionError("Personal Substrate session requires a reusable Microsoft cookie")
    result["cookies"] = normalized_cookies
    for key in ("local_storage", "session_storage"):
        storage = value.get(key)
        if not isinstance(storage, dict) or len(storage) > 256:
            raise PersonalSubstrateSessionError("Personal Substrate storage must be a bounded string map")
        result[key] = {bounded_string(k, 2048): bounded_string(v) for k, v in storage.items()}
    if "broker" in value:
        result["broker"] = _normalize_broker_grant(value["broker"], bounded_string)
    return result


def _normalize_broker_grant(broker: object, bounded_string) -> dict:
    """A refresh grant the page itself redeemed, pinned to the personal token endpoint."""
    if not isinstance(broker, dict) or set(broker) != {"refresh_token", "expires_at", "url", "form"}:
        raise PersonalSubstrateSessionError("Personal Substrate broker grant is malformed")
    refresh_token = bounded_string(broker["refresh_token"], 16 * 1024)
    if not refresh_token or any(ord(char) <= 32 or ord(char) == 127 for char in refresh_token):
        raise PersonalSubstrateSessionError("Personal Substrate broker grant is malformed")
    url = bounded_string(broker["url"], 4096)
    try:
        parsed = urlsplit(url)
        pinned = (
            parsed.scheme == "https" and parsed.hostname == PERSONAL_TOKEN_HOST
            and not parsed.username and not parsed.password and parsed.port in (None, 443)
            and parsed.path in PERSONAL_TOKEN_PATHS and not parsed.fragment
        )
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=bool(parsed.query))
    except ValueError:
        pinned = False
    if not pinned or set(query) - BROKER_QUERY_KEYS or any(len(values) != 1 for values in query.values()):
        raise PersonalSubstrateSessionError("Personal Substrate broker endpoint is not allowed")
    form = broker["form"]
    if not isinstance(form, dict) or not form.get("client_id") or set(form) - BROKER_FORM_KEYS:
        raise PersonalSubstrateSessionError("Personal Substrate broker form is malformed")
    return {
        "refresh_token": refresh_token,
        "expires_at": normalize_personal_substrate_expiry(broker["expires_at"]),
        "url": url,
        "form": {key: bounded_string(item, 4096) for key, item in form.items()},
    }


def has_usable_personal_substrate_session(token: str, account_id: str, session: object) -> bool:
    from .token_store import is_valid_substrate_jwe

    if not is_valid_substrate_jwe(token):
        return False
    try:
        normalize_personal_substrate_session(session, account_id)
    except (ValueError, TypeError, OverflowError):
        return False
    return True
