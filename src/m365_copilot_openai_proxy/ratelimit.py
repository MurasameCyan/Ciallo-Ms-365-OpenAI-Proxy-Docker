"""Thread-safe token-bucket rate limiter for per-key request throttling.

Microsoft 365 Copilot chat publishes no explicit rate limit headers, so this is
a *self-imposed* ceiling: a safety valve that keeps automated callers or shared
keys from hammering a single signed-in account and triggering upstream throttling.

Token bucket: the bucket holds at most ``burst`` tokens and refills at
``rpm / 60`` tokens per second. Each request spends one token. When the bucket
is empty the request is refused with a retry-after value, so short bursts are
absorbed up to ``burst`` while the long-run average is held at ``rpm``.
"""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """Classic token bucket. ``try_acquire`` is non-blocking and thread-safe."""

    def __init__(self, rpm: float, burst: int, *, monotonic=None):
        # rpm <= 0 disables limiting entirely (every acquire succeeds).
        self.rpm = float(rpm)
        self.rate = self.rpm / 60.0  # tokens per second
        self.capacity = max(1, int(burst))
        self._tokens = float(self.capacity)
        self._lock = threading.Lock()
        # Injectable clock keeps this unit-testable without real time passing.
        self._now = monotonic or time.monotonic
        self._updated = self._now()

    @property
    def enabled(self) -> bool:
        return self.rpm > 0

    def _refill(self, now: float) -> None:
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._updated = now

    def try_acquire(self) -> tuple[bool, float]:
        """Spend one token if available.

        Returns ``(allowed, retry_after_seconds)``. When disabled, always
        ``(True, 0.0)``. When refused, ``retry_after`` is the time until one
        token has accrued (always > 0).
        """
        if not self.enabled:
            return True, 0.0
        with self._lock:
            now = self._now()
            self._refill(now)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True, 0.0
            # Time until the bucket reaches one whole token.
            deficit = 1.0 - self._tokens
            retry_after = deficit / self.rate if self.rate > 0 else 0.0
            return False, retry_after


class RateLimiterRegistry:
    """Holds one TokenBucket per identity, rebuilt when its limit changes.

    The bucket must outlive a single request to mean anything, and it cannot
    live on the ApiKey: KeyStore.update() replaces the dataclass instance, which
    would silently reset the bucket (and hand out a full burst) on every admin
    edit. Keying by the key's id keeps the accrued state across those rebuilds.

    ponytail: entries are never evicted. One bucket is ~100 bytes and ids come
    from the key table, so the ceiling is the number of keys ever resolved this
    process -- not worth a reaper. Revoking a key leaves a stale bucket that
    simply stops being consulted; if key churn ever becomes unbounded, drop
    entries whose id is no longer in KeyStore on a keepalive tick.
    """

    def __init__(self):
        self._buckets: dict[str, tuple[float, int, TokenBucket]] = {}
        self._lock = threading.Lock()

    def try_acquire(self, identity: str, rpm: float, burst: int) -> tuple[bool, float]:
        """Spend one token for ``identity`` against the (rpm, burst) limit.

        A changed rpm/burst replaces the bucket, so an admin lowering the limit
        takes effect on the next request instead of after the old bucket drains.
        """
        if rpm <= 0:
            return True, 0.0
        with self._lock:
            entry = self._buckets.get(identity)
            if entry is None or entry[0] != rpm or entry[1] != burst:
                bucket = TokenBucket(rpm, burst)
                self._buckets[identity] = (rpm, burst, bucket)
            else:
                bucket = entry[2]
        return bucket.try_acquire()

