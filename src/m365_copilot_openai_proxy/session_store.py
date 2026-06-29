from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CopilotTurn:
    conversation_id: str
    client_session_id: str
    is_start_of_session: bool


@dataclass
class PersistentSession:
    conversation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client_session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    turn_count: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def reserve_turn(self) -> CopilotTurn:
        turn = CopilotTurn(
            conversation_id=self.conversation_id,
            client_session_id=self.client_session_id,
            is_start_of_session=self.turn_count == 0,
        )
        self.turn_count += 1
        return turn


class PersistentSessionStore:
    def __init__(self):
        self._sessions: dict[str, PersistentSession] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> PersistentSession:
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                session = PersistentSession()
                self._sessions[key] = session
            return session
