from __future__ import annotations

import time


class LoginRateLimiter:
    """Per-IP failed-login throttle shared by the admin and user logins.

    Tracks recent failed attempts per client IP and locks the IP out once it
    exceeds ``limit`` failures within ``lockout_sec``. Successful logins clear
    the counter. Empty entries are pruned on every check so the failure map
    cannot grow without bound from one-off attempts across many IPs.
    """

    def __init__(self, limit: int = 5, lockout_sec: float = 60.0):
        self._limit = limit
        self._lockout = lockout_sec
        self._failures: dict[str, list[float]] = {}

    def is_locked(self, ip: str) -> bool:
        """True if ``ip`` has too many recent failures (also prunes stale ones)."""
        now = time.time()
        recent = [t for t in self._failures.get(ip, []) if now - t < self._lockout]
        if recent:
            self._failures[ip] = recent
        else:
            self._failures.pop(ip, None)
        return len(recent) >= self._limit

    def record_failure(self, ip: str) -> None:
        """Record one failed attempt for ``ip``."""
        self._failures.setdefault(ip, []).append(time.time())

    def clear(self, ip: str) -> None:
        """Forget all failures for ``ip`` (called on a successful login)."""
        self._failures.pop(ip, None)
