from __future__ import annotations

import hmac
import re

# Login credential rules (validated server-side; front-end checks are bypassable).
# Username: letters + digits only. Password: letters, digits, and a safe symbol
# subset that excludes quotes/backslash/angle brackets/whitespace so credentials
# can never break out of JSON, HTML attributes, or shell contexts.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9]{1,32}$")
_PASSWORD_RE = re.compile(r"^[A-Za-z0-9!#$%&*+\-.:=?@^_~]{6,64}$")


def _validate_username(username: str) -> str | None:
    if not _USERNAME_RE.match(username):
        return "Username must be 1-32 chars, letters and digits only"
    return None


def _validate_password(password: str) -> str | None:
    if not _PASSWORD_RE.match(password):
        return "Password must be 6-64 chars: letters, digits, and safe symbols (!#$%&*+-.:=?@^_~)"
    return None


def constant_time_equals(left: str, right: str) -> bool:
    """Constant-time string compare that tolerates non-ASCII input.

    ``secrets.compare_digest`` raises TypeError on str arguments holding any
    codepoint above U+007F, and every caller here compares a secret against a
    value an outside caller chose: an admin password from a request body, a
    signature segment from a request body, a cookie. Measured with a live
    TestClient, one non-ASCII character in the ``/admin/login`` body was an
    unhandled HTTP 500 -- and because the exception fires before any comparison,
    an admin whose ADMIN_PASSWORD contains non-ASCII characters could never log
    in *even with the correct password*, since the failure is identical for right
    and wrong guesses.

    Comparing UTF-8 bytes keeps the timing guarantee (compare_digest's bytes path
    is the same primitive) while making a non-ASCII secret merely wrong rather
    than fatal. ``surrogatepass`` is required because a mangled header or JSON
    escape can carry a lone surrogate, which plain UTF-8 encoding rejects with
    UnicodeEncodeError -- trading one unhandled exception for another.
    """
    return hmac.compare_digest(
        left.encode("utf-8", "surrogatepass"),
        right.encode("utf-8", "surrogatepass"),
    )
