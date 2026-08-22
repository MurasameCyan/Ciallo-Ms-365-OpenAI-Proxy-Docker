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

Client-visible message content is hashed in a stable form: plain text is
whitespace-normalized, while structured blocks (including Anthropic
``tool_use``/``tool_result`` blocks) are serialized with sorted keys. The
recorded prefix is exactly what the client resends, so a match does not depend on
how a client renders content internally. Digests are stored under the caller's
tenant, so one tenant can never match into another tenant's session. If the
index cannot place a continuation (for example, after a client trims old
messages or the process restarts), the caller starts a fresh upstream session
and resends the client-supplied history. This is deliberately safer than using
the legacy first-message key, because multiple Cherry conversations commonly
share the same opener.

The index is exact by design: no fuzzy/similarity matching, which could glue two
unrelated conversations of the same user together. A continuation that misses
the index starts a fresh upstream conversation with the client-supplied history
instead of reusing the legacy first-message key.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict

from .translator import flatten_content

# Roughly four conversations' worth of turns per tenant for a busy pool; the
# session store itself only keeps 1000 sessions, so a larger index would just
# hold digests for sessions that no longer exist.
_MAX_ENTRIES = 4096
_MAX_OWNERS_PER_ENTRY = 2


def normalize_history(messages) -> list[tuple[str, str]]:
    """Reduce messages to comparable (role, content-signature) pairs.

    System messages are dropped on purpose: clients routinely inject a system
    prompt that changes every turn (current time, cwd, tool inventory), which
    would break the chain on every single turn. Whitespace is collapsed so a
    client re-wrapping its own text still matches. Non-text blocks are retained
    as canonical JSON so Anthropic tool continuations remain on their session.
    """
    pairs: list[tuple[str, str]] = []
    for msg in messages:
        role = (
            msg.get("role", "")
            if isinstance(msg, dict)
            else getattr(msg, "role", "")
        ) or ""
        if role not in ("user", "assistant", "tool"):
            continue
        content = (
            msg.get("content")
            if isinstance(msg, dict)
            else getattr(msg, "content", None)
        )
        if isinstance(content, list) and any(
            isinstance(part, dict) for part in content
        ):
            text_content = "".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            text_content = flatten_content(content)
        text = " ".join(text_content.split())
        structured: list[str] = []
        if isinstance(content, list):
            for part in content:
                part_type = (
                    part.get("type")
                    if isinstance(part, dict)
                    else getattr(part, "type", None)
                )
                if part_type == "text":
                    continue
                if hasattr(part, "model_dump"):
                    value = part.model_dump(mode="json", exclude_none=True)
                elif isinstance(part, dict):
                    value = part
                else:
                    value = str(part)
                structured.append(
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
        tool_calls = (
            msg.get("tool_calls")
            if isinstance(msg, dict)
            else getattr(msg, "tool_calls", None)
        )
        if tool_calls:
            values = [
                part.model_dump(mode="json", exclude_none=True)
                if hasattr(part, "model_dump")
                else part
                for part in tool_calls
            ]
            structured.append(
                "tool_calls="
                + json.dumps(
                    values,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        for field in ("tool_call_id", "name"):
            value = msg.get(field) if isinstance(msg, dict) else getattr(msg, field, None)
            if value:
                structured.append(f"{field}={value}")
        signature = "\n".join(part for part in (text, *structured) if part)
        if signature:
            pairs.append((role, signature))
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
        self._entries: OrderedDict[str, set[str]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_entries = max_entries
        # Counters for the admin cache panel: a miss means a continuation starts
        # a new upstream conversation with the full client history.
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _entry(tenant: str, digest: str) -> str:
        # NUL cannot appear in a tenant id, so the join is unambiguous.
        return f"{tenant}\0{digest}"

    def stats(self) -> dict:
        with self._lock:
            looked_up = self.hits + self.misses
            return {
                "entries": len(self._entries),
                "max_entries": self._max_entries,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / looked_up, 4) if looked_up else None,
            }

    def match(self, tenant: str, pairs: list[tuple[str, str]]) -> str | None:
        """Return the unique owner of the longest safe strict history prefix.

        A prefix owned by multiple upstream sessions is not safe to resume:
        choosing either owner would leak context, so the caller must start fresh
        instead. A unique user-only prefix is safe when no competing owner is
        recorded, which is required for the normal first-turn continuation.
        """
        digests = _chain(pairs)
        with self._lock:
            for position in range(len(digests) - 2, -1, -1):
                digest = digests[position]
                entry = self._entry(tenant, digest)
                keys = self._entries.get(entry)
                if keys is not None:
                    self._entries.move_to_end(entry)
                    if len(keys) == 1:
                        self.hits += 1
                        return next(iter(keys))
                    self.misses += 1
                    return None
            self.misses += 1
        return None

    def record(self, tenant: str, pairs: list[tuple[str, str]], store_key: str) -> None:
        """Remember that this exact history belongs to `store_key`."""
        digests = _chain(pairs)
        if not digests:
            return
        entry = self._entry(tenant, digests[-1])
        with self._lock:
            owners = self._entries.setdefault(entry, set())
            # Matching only distinguishes a unique owner from an ambiguous
            # prefix. Additional owners add no information and would let a
            # repeated templated opener grow one set without bound.
            if len(owners) < _MAX_OWNERS_PER_ENTRY:
                owners.add(store_key)
            self._entries.move_to_end(entry)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
