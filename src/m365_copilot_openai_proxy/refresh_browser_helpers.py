from __future__ import annotations

from .account_store import extract_identity


def _is_login_url(url: str) -> bool:
    return url.startswith(("https://login.microsoftonline.com/", "https://login.live.com/"))


def _is_logged_out_shell(url: str) -> bool:
    """True when M365 loaded the chat shell but WITHOUT a signed-in account.

    m365.cloud.microsoft redirects to `...chat?from=NoAccountOnStart` (and
    similar markers) when the injected cookies did not actually establish a
    session. The URL is not a login page, so `_is_login_url` misses it, yet the
    page has no usable identity -- treating it as "logged in" produces a false
    "cookie valid" state that later fails on refresh. Detect those markers so
    the caller can treat the shell as logged-out.
    """
    lowered = url.lower()
    return any(marker in lowered for marker in ("noaccountonstart", "from=noaccount"))


def _identity_conflict(existing_email: str, new_token: str) -> bool:
    """True when a freshly captured token belongs to a DIFFERENT identity.

    The persistent Chromium profile can retain another Microsoft account's
    session (e.g. a previously injected account), so an on-demand refresh may
    capture a token for the wrong identity and silently overwrite the record.
    Reject the swap when both the stored account and the new token carry an
    email and they differ. When either side has no email we cannot compare, so
    we do not block (first-time capture / opaque token stays permissive).
    """
    existing = (existing_email or "").strip().lower()
    if not existing:
        return False
    _, new_email = extract_identity(new_token)
    new_email = (new_email or "").strip().lower()
    if not new_email:
        return False
    return existing != new_email


def _refresh_launch_url(login_hint: str = "") -> str:
    """M365 chat launch URL for on-demand refresh, biased to login_hint.

    Delegates to cli._m365_chat_url (lazy import to avoid the cli <-> app <->
    scheduler import cycle). Falls back to the plain chat URL if the import
    fails, so a helper regression can never break Chromium launch.
    """
    try:
        from .cli import _m365_chat_url

        return _m365_chat_url(login_hint)
    except Exception:
        return "https://m365.cloud.microsoft/chat"
