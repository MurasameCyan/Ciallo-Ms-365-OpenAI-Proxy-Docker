from __future__ import annotations

"""Process-wide toggles for the account/refresh runtime logs.

These logs are emitted via bare ``print`` from deep helpers (RT refresh, cookie
injection, media-auth capture, keepalive, ...) that have no access to
``app.state``. Threading state through every call site is invasive, so the
toggles live here as module-level globals and are updated in one place from the
admin settings / startup wiring.

Two independent switches:
  * ``VERBOSE_USER_LOGS`` gates normal progress logs (``ulog``): seeded MSAL,
    captured token, harvested/captured media, keepalive ticks, RT success, etc.
  * ``ERROR_USER_LOGS`` gates failure/exception logs (``elog``): refresh failed,
    identity mismatch, capture skipped, etc.

Both default to True so behaviour is unchanged until explicitly turned off.
Startup wiring seeds them from the .env / runtime settings; the admin settings
endpoint overrides them at runtime.

A third switch, ``SUPPRESS_ACCESS_LOG``, gates the uvicorn access-log filter in
cli.py (high-frequency admin/user polling, health checks, favicon, root and
media-proxy hits). It lives here too because that filter is registered at module
import and has no access to ``app.state``; reading the module attribute lets the
admin UI flip it at runtime. Defaults to True (noisy access lines suppressed).
"""

VERBOSE_USER_LOGS: bool = True
ERROR_USER_LOGS: bool = True
SUPPRESS_ACCESS_LOG: bool = True


def set_flags(
    *,
    verbose: bool | None = None,
    errors: bool | None = None,
    suppress_access_log: bool | None = None,
) -> None:
    """Update the module-level toggles in place (None leaves a flag unchanged)."""
    global VERBOSE_USER_LOGS, ERROR_USER_LOGS, SUPPRESS_ACCESS_LOG
    if verbose is not None:
        VERBOSE_USER_LOGS = bool(verbose)
    if errors is not None:
        ERROR_USER_LOGS = bool(errors)
    if suppress_access_log is not None:
        SUPPRESS_ACCESS_LOG = bool(suppress_access_log)


def ulog(msg: str) -> None:
    """Print a normal user/account runtime log iff verbose logging is enabled."""
    if VERBOSE_USER_LOGS:
        print(msg, flush=True)


def elog(msg: str) -> None:
    """Print an error/failure user log iff error logging is enabled."""
    if ERROR_USER_LOGS:
        print(msg, flush=True)
