from __future__ import annotations

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
