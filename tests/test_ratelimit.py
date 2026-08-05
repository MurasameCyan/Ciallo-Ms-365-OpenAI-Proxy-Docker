from __future__ import annotations

from m365_copilot_openai_proxy.ratelimit import RateLimiterRegistry, TokenBucket


class FakeClock:
    """Hand-cranked monotonic clock so refill behaviour is testable instantly."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_burst_is_spendable_immediately():
    bucket = TokenBucket(rpm=60, burst=5, monotonic=FakeClock())

    for _ in range(5):
        allowed, retry_after = bucket.try_acquire()
        assert allowed
        assert retry_after == 0.0


def test_refuses_once_burst_is_drained():
    bucket = TokenBucket(rpm=60, burst=3, monotonic=FakeClock())
    for _ in range(3):
        bucket.try_acquire()

    allowed, retry_after = bucket.try_acquire()

    assert not allowed
    # 60 rpm == 1 token/sec, so a full token is one second away.
    assert retry_after == 1.0


def test_tokens_refill_over_time():
    clock = FakeClock()
    bucket = TokenBucket(rpm=60, burst=2, monotonic=clock)
    bucket.try_acquire()
    bucket.try_acquire()
    assert bucket.try_acquire()[0] is False

    clock.advance(1.0)

    assert bucket.try_acquire()[0] is True
    assert bucket.try_acquire()[0] is False


def test_refill_never_exceeds_capacity():
    """An idle bucket must not bank tokens beyond its burst depth."""
    clock = FakeClock()
    bucket = TokenBucket(rpm=60, burst=3, monotonic=clock)

    clock.advance(3600)

    for _ in range(3):
        assert bucket.try_acquire()[0] is True
    assert bucket.try_acquire()[0] is False


def test_zero_rpm_disables_limiting():
    bucket = TokenBucket(rpm=0, burst=1, monotonic=FakeClock())

    for _ in range(100):
        assert bucket.try_acquire() == (True, 0.0)


def test_registry_keeps_separate_buckets_per_identity():
    registry = RateLimiterRegistry()

    for _ in range(2):
        assert registry.try_acquire("alice", rpm=60, burst=2)[0] is True
    assert registry.try_acquire("alice", rpm=60, burst=2)[0] is False

    # Bob's budget is untouched by Alice draining hers.
    assert registry.try_acquire("bob", rpm=60, burst=2)[0] is True


def test_registry_preserves_bucket_across_calls():
    registry = RateLimiterRegistry()

    assert registry.try_acquire("alice", rpm=60, burst=1)[0] is True
    assert registry.try_acquire("alice", rpm=60, burst=1)[0] is False


def test_registry_rebuilds_bucket_when_limit_changes():
    """An admin lowering (or raising) a limit takes effect on the next request."""
    registry = RateLimiterRegistry()
    registry.try_acquire("alice", rpm=60, burst=1)
    assert registry.try_acquire("alice", rpm=60, burst=1)[0] is False

    assert registry.try_acquire("alice", rpm=120, burst=5)[0] is True


def test_registry_treats_non_positive_rpm_as_unlimited():
    registry = RateLimiterRegistry()

    for _ in range(50):
        assert registry.try_acquire("alice", rpm=0, burst=1) == (True, 0.0)
