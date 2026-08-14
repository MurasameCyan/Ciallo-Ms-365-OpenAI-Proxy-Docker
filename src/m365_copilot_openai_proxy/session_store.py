from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class CopilotTurn:
    conversation_id: str
    client_session_id: str
    is_start_of_session: bool


_MAX_SESSIONS = 1000


@dataclass
class PersistentSession:
    conversation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client_session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    turn_count: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    response_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    last_accessed: float = field(default_factory=time.time)
    issued_response_calls: dict[str, list[str]] = field(default_factory=dict)
    issued_response_read_only: dict[str, bool] = field(default_factory=dict)
    consumed_response_ids: list[str] = field(default_factory=list)
    latest_response_id: str | None = None
    pending_response_ids: dict[str, str] = field(default_factory=dict, repr=False)
    # Called after turn_count changes so the store can persist to disk.
    _on_change: Callable[[], None] | None = field(default=None, repr=False, compare=False)

    def reserve_turn(self) -> CopilotTurn:
        turn = CopilotTurn(
            conversation_id=self.conversation_id,
            client_session_id=self.client_session_id,
            is_start_of_session=self.turn_count == 0,
        )
        self.turn_count += 1
        self.last_accessed = time.time()
        if self._on_change is not None:
            self._on_change()
        return turn

    def record_response(
        self,
        response_id: str,
        call_ids: list[str],
        read_only: bool = False,
    ) -> None:
        """Remember issued Responses ids and their function calls for continuation."""
        self.issued_response_calls[response_id] = list(dict.fromkeys(call_ids))
        self.issued_response_read_only[response_id] = read_only
        self.latest_response_id = response_id
        while len(self.issued_response_calls) > 64:
            expired = next(iter(self.issued_response_calls))
            self.issued_response_calls.pop(expired)
            self.issued_response_read_only.pop(expired, None)
        self.last_accessed = time.time()
        if self._on_change is not None:
            self._on_change()

    def allows_response_outputs(self, response_id: str, call_ids: set[str]) -> bool:
        issued = self.issued_response_calls.get(response_id)
        return (
            response_id == self.latest_response_id
            and issued is not None
            and call_ids == set(issued)
        )

    def response_is_read_only(self, response_id: str) -> bool:
        return self.issued_response_read_only.get(response_id, False)

    def begin_response_continuation(self, response_id: str) -> str | None:
        """Reserve an issued response id for one in-flight continuation."""
        if response_id not in self.issued_response_calls:
            return None
        if response_id != self.latest_response_id:
            return None
        if response_id in self.consumed_response_ids:
            return None
        if response_id in self.pending_response_ids:
            return None
        reservation = uuid.uuid4().hex
        self.pending_response_ids[response_id] = reservation
        return reservation

    def finish_response_continuation(
        self,
        response_id: str,
        reservation: str,
        success: bool,
    ) -> None:
        """Commit a successful linear continuation, or release a failed one."""
        if self.pending_response_ids.get(response_id) != reservation:
            return
        del self.pending_response_ids[response_id]
        if not success:
            return
        self.consumed_response_ids.append(response_id)
        while len(self.consumed_response_ids) > 64:
            self.consumed_response_ids.pop(0)
        self.last_accessed = time.time()
        if self._on_change is not None:
            self._on_change()

    def complete_response_continuation(
        self,
        parent_response_id: str,
        reservation: str,
        child_response_id: str,
        child_call_ids: list[str],
        child_read_only: bool = False,
    ) -> bool:
        """Atomically record the child response and consume its linear parent."""
        if self.pending_response_ids.get(parent_response_id) != reservation:
            return False
        del self.pending_response_ids[parent_response_id]
        self.consumed_response_ids.append(parent_response_id)
        while len(self.consumed_response_ids) > 64:
            self.consumed_response_ids.pop(0)
        self.issued_response_calls[child_response_id] = list(
            dict.fromkeys(child_call_ids)
        )
        self.issued_response_read_only[child_response_id] = child_read_only
        self.latest_response_id = child_response_id
        while len(self.issued_response_calls) > 64:
            expired = next(iter(self.issued_response_calls))
            self.issued_response_calls.pop(expired)
            self.issued_response_read_only.pop(expired, None)
        self.last_accessed = time.time()
        if self._on_change is not None:
            self._on_change()
        return True


class PersistentSessionStore:
    def __init__(self, max_sessions: int = _MAX_SESSIONS, persist_path: str | Path | None = None):
        self._sessions: OrderedDict[str, PersistentSession] = OrderedDict()
        self._lock = threading.RLock()
        self._max_sessions = max_sessions
        self._persist_path = Path(persist_path) if persist_path else None
        if self._persist_path is not None:
            self._load()

    def _load(self) -> None:
        """Restore sessions from disk so conversations survive container restarts."""
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError, OSError):
            return
        if not isinstance(data, dict):
            return
        for key, s in data.items():
            if not isinstance(s, dict):
                continue
            issued_response_calls = s.get("issued_response_calls", {}) or {}
            if not isinstance(issued_response_calls, dict):
                issued_response_calls = {}
            clean_issued_response_calls = {
                str(response_id): [
                    str(call_id)
                    for call_id in call_ids
                    if isinstance(call_id, str)
                ]
                for response_id, call_ids in issued_response_calls.items()
                if isinstance(response_id, str) and isinstance(call_ids, list)
            }
            issued_response_read_only = s.get("issued_response_read_only", {}) or {}
            if not isinstance(issued_response_read_only, dict):
                issued_response_read_only = {}
            consumed_response_ids = s.get("consumed_response_ids", []) or []
            if not isinstance(consumed_response_ids, list):
                consumed_response_ids = []
            latest_response_id = s.get("latest_response_id")
            if latest_response_id not in clean_issued_response_calls:
                latest_response_id = next(reversed(clean_issued_response_calls), None)
            try:
                session = PersistentSession(
                    conversation_id=s["conversation_id"],
                    client_session_id=s["client_session_id"],
                    turn_count=int(s.get("turn_count", 0)),
                    last_accessed=float(s.get("last_accessed", time.time())),
                    issued_response_calls=clean_issued_response_calls,
                    issued_response_read_only={
                        response_id: value
                        for response_id, value in issued_response_read_only.items()
                        if (
                            isinstance(response_id, str)
                            and response_id in clean_issued_response_calls
                            and isinstance(value, bool)
                        )
                    },
                    consumed_response_ids=[
                        str(response_id)
                        for response_id in consumed_response_ids
                        if isinstance(response_id, str)
                    ][-64:],
                    latest_response_id=latest_response_id,
                )
            except (KeyError, TypeError, ValueError):
                continue
            session._on_change = self._save
            self._sessions[key] = session

    def _save(self) -> None:
        """Atomically write the session map to disk (best-effort)."""
        if self._persist_path is None:
            return
        with self._lock:
            data = {
                key: {
                    "conversation_id": s.conversation_id,
                    "client_session_id": s.client_session_id,
                    "turn_count": s.turn_count,
                    "last_accessed": s.last_accessed,
                    "issued_response_calls": s.issued_response_calls,
                    "issued_response_read_only": s.issued_response_read_only,
                    "consumed_response_ids": s.consumed_response_ids,
                    "latest_response_id": s.latest_response_id,
                }
                for key, s in self._sessions.items()
            }
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._persist_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self._persist_path)
        except OSError:
            pass  # Persistence is best-effort; never break a request over a disk error

    def get(self, key: str) -> PersistentSession:
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                session = PersistentSession()
                session._on_change = self._save
                self._sessions[key] = session
                # Evict oldest session if over limit
                while len(self._sessions) > self._max_sessions:
                    self._sessions.popitem(last=False)
                self._save()
            else:
                # Move to end (most recently used)
                self._sessions.move_to_end(key)
                session.last_accessed = time.time()
            return session

    def key_for(self, session: PersistentSession) -> str | None:
        """Return the storage key for an existing session object."""
        with self._lock:
            return next(
                (key for key, candidate in self._sessions.items() if candidate is session),
                None,
            )

    def get_existing(self, key: str) -> PersistentSession | None:
        """Return an existing session without creating an attacker-chosen key."""
        with self._lock:
            session = self._sessions.get(key)
            if session is not None:
                self._sessions.move_to_end(key)
                session.last_accessed = time.time()
            return session

    def reset(self, key: str) -> PersistentSession:
        """Discard any existing session under key and start a fresh one.

        Used when the auto-detected conversation key collides (e.g. two different
        conversations that happen to share the same first user message): a new
        conversation's first turn must NOT reuse the previous M365 thread, or the
        model receives stale context and hallucinates. A fresh session gets a new
        conversation_id / client_session_id and turn_count=0.
        """
        with self._lock:
            session = PersistentSession()
            session._on_change = self._save
            self._sessions[key] = session
            self._sessions.move_to_end(key)
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)
            self._save()
            return session
