"""The one usage number upstream actually counts for us, kept per account.

WHY THIS IS NOT IN `usage_store`. Everything there is an ESTIMATE: this protocol
sends no token counts at all, which three independent clients
(`kdeps/kdeps`, `chrischall/opencode-copilot-plugin`, `HEXUXIU/M365-Copilot2API`)
independently confirm by reporting zeros or estimating too. What upstream DOES
count is how many user messages a conversation has spent against its ceiling,
and until now we read only the `Throttled` verdict off a failed turn and dropped
the counters that came with it.

Mixing the two would be a category error twice over: this counts MESSAGES, not
tokens, so it cannot be summed into a token total; and it is a per-CONVERSATION
gauge that resets with the conversation, so it cannot be accumulated the way
`usage_store` accumulates a monotonic lifetime total. Hence a separate, small,
in-memory gauge.

WHY IN MEMORY, NOT PERSISTED. It is a live reading whose only value is being
current. A number reloaded from disk after a restart describes conversations that
may no longer exist, and a stale quota is worse than no quota because it looks
authoritative. Losing it on restart is correct.

LATEST WINS, including backwards. The server is the only authority; if it reports
a lower count later (a new conversation on the same account) that is the truth,
not an anomaly to be maxed away.
"""
from __future__ import annotations

import threading
import time
from typing import Any


class ConversationQuotaStore:
    """Newest quota per account. Bounded readings, unpersisted, thread-safe."""

    # An account id per entry and a handful of ints; the cap only exists so a
    # long-lived process with many rotated accounts cannot grow without bound.
    _MAX_ACCOUNTS = 200

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_account: dict[str, dict[str, Any]] = {}
        # Account ids are never reused. Keep deletions for this process's
        # lifetime: evicting one would let an old in-flight callback revive it.
        # Unlike readings, these contain only ids; restart drops all callbacks
        # as well as these tombstones, so neither needs persistence.
        self._forgotten: set[str] = set()

    def record(self, account_id: str, quota: dict[str, int] | None) -> None:
        """Store one reading. A falsy quota is ignored, never stored as zeros."""
        account_id = str(account_id or "").strip()
        if not account_id or not quota:
            return
        messages = quota.get("messages")
        maximum = quota.get("max_messages")
        if not isinstance(messages, int) or not isinstance(maximum, int):
            return
        entry: dict[str, Any] = {
            "messages": max(0, messages),
            "max_messages": max(0, maximum),
            "ts": time.time(),
        }
        long_doc = quota.get("long_doc_messages")
        if isinstance(long_doc, int):
            entry["long_doc_messages"] = max(0, long_doc)
        # Percent and remaining are derived here rather than in the template so
        # every reader agrees on them. `max` of 0 would be a division by zero and
        # is treated as "no ceiling stated" rather than "no quota left".
        if entry["max_messages"] > 0:
            entry["remaining"] = max(0, entry["max_messages"] - entry["messages"])
            entry["percent"] = min(
                100, round(entry["messages"] / entry["max_messages"] * 100, 2)
            )
        with self._lock:
            if account_id in self._forgotten:
                return
            self._by_account[account_id] = entry
            if len(self._by_account) > self._MAX_ACCOUNTS:
                # Drop the least recently reported, not an arbitrary one.
                oldest = min(
                    self._by_account,
                    key=lambda key: self._by_account[key].get("ts", 0.0),
                )
                self._by_account.pop(oldest, None)

    def stats(self) -> dict[str, dict[str, Any]]:
        """Every account that has reported, for the admin snapshot."""
        with self._lock:
            return {
                account_id: dict(entry)
                for account_id, entry in sorted(self._by_account.items())
            }

    def forget(self, account_id: str) -> None:
        """Drop one account's reading, because the account itself is gone.

        Deliberately this rather than a generic ``clear()``: a quota row that
        outlives its account is exactly the stale-authority problem this
        module's header rejects. `/admin/stats` would keep showing a spent
        count for an identity that no longer exists. A turn already in flight
        can still report after deletion, so remember the deletion under the
        same lock as record(). Wired to the account-deletion route beside
        `key_store.detach_account`, which cleans up the other dangling reference.
        """
        account_id = str(account_id or "").strip()
        if not account_id:
            return
        with self._lock:
            self._forgotten.add(account_id)
            self._by_account.pop(account_id, None)
