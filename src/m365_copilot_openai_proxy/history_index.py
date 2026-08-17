"""Exact history digest index: map a client's message history to the session
that already owns the upstream conversation.

The auto-detected session key hashes only the FIRST user message (see
``_detect_conversation_session``), so every conversation that opens with the same
text shares one key -- and agent frameworks routinely open every conversation
with the same templated message. Sharing a key means the newest conversation
resets the session the others are running on, and their next turn then continues
inside the wrong upstream thread. This index identifies a conversation by its
whole history instead: every turn records a chained digest of its normalized
messages, and the next turn of that same conversation -- whose message list
contains that list as a strict prefix -- finds the session back by matching the
longest known prefix.

Only client-authored text is ever hashed: the recorded prefix is exactly what the
client resends verbatim, so a match never depends on how a client re-renders our
assistant reply. Digests are stored under the caller's tenant, so one tenant can
never match into another tenant's session. Whatever the index cannot place (a
client that trims old messages, or a restart that emptied the index) falls back
to the legacy first-message key, which is where the session already is.

The index is exact by design: no fuzzy/similarity matching, which could glue two
unrelated conversations of the same user together.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

from .translator import flatten_content

# Roughly four conversations' worth of turns per tenant for a busy pool; the
# session store itself only keeps 1000 sessions, so a larger index would just
# hold digests for sessions that no longer exist.
_MAX_ENTRIES = 4096


def normalize_history(messages) -> list[tuple[str, str]]:
    """Reduce a request's messages to comparable (role, text) pairs.

    System messages are dropped on purpose: clients routinely inject a system
    prompt that changes every turn (current time, cwd, tool inventory), which
    would break the chain on every single turn. Whitespace is collapsed so a
    client re-wrapping its own text still matches.
    """
    pairs: list[tuple[str, str]] = []
    for msg in messages:
        role = getattr(msg, "role", "") or ""
        if role not in ("user", "assistant"):
            continue
        text = " ".join(flatten_content(getattr(msg, "content", None)).split())
        if text:
            pairs.append((role, text))
    return pairs


def _chain(pairs: list[tuple[str, str]]) -> list[str]:
    """Digest of every prefix in one pass: result[i] covers pairs[:i + 1]."""
    running = hashlib.sha256()
    digests: list[str] = []
    for role, text in pairs:
        running.update(role.encode())
        running.update(b"\x00")
        running.update(text.encode())
        running.update(b"\x00")
        digests.append(running.hexdigest())
    return digests


class HistoryDigestIndex:
    """Tenant-scoped map from a history digest to a session store key."""

    def __init__(self, max_entries: int = _MAX_ENTRIES):
        self._entries: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()
        self._max_entries = max_entries

    @staticmethod
    def _entry(tenant: str, digest: str) -> str:
        # NUL cannot appear in a tenant id, so the join is unambiguous.
        return f"{tenant}\0{digest}"

    def match(self, tenant: str, pairs: list[tuple[str, str]]) -> str | None:
        """Store key owning the longest *strict* prefix of this history.

        Strict matters: the full history is what this turn records, so matching
        it would make a resend of the same turn look like a continuation.
        """
        digests = _chain(pairs)
        with self._lock:
            for digest in reversed(digests[:-1]):
                entry = self._entry(tenant, digest)
                key = self._entries.get(entry)
                if key is not None:
                    self._entries.move_to_end(entry)
                    return key
        return None

    def record(self, tenant: str, pairs: list[tuple[str, str]], store_key: str) -> None:
        """Remember that this exact history belongs to `store_key`."""
        digests = _chain(pairs)
        if not digests:
            return
        entry = self._entry(tenant, digests[-1])
        with self._lock:
            self._entries[entry] = store_key
            self._entries.move_to_end(entry)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def is_taken(self, tenant: str, store_key: str, pairs: list[tuple[str, str]]) -> bool:
        """True when a chain other than this exact history owns `store_key`.

        Asked before a brand-new conversation claims a key, so it can move aside
        instead of evicting a conversation that is still running on it. A resend
        of the same opening turn is not "taken" -- that is the same conversation
        restarting, which should keep its key.

        ponytail: linear scan over at most `_MAX_ENTRIES` entries, on first turns
        only (once per conversation, next to a multi-second upstream round trip).
        If that ever shows up in a profile, keep a reverse key -> entries map.
        """
        digests = _chain(pairs)
        own = self._entry(tenant, digests[-1]) if digests else ""
        prefix = f"{tenant}\0"
        with self._lock:
            return any(
                value == store_key and entry != own and entry.startswith(prefix)
                for entry, value in self._entries.items()
            )
