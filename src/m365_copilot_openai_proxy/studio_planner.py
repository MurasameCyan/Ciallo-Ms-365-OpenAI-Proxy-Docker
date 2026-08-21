from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .session_store import PersistentSession
from .substrate_client import SubstrateCopilotError, SubstrateThrottled


class ChatStreamClient(Protocol):
    def chat_stream(
        self,
        prompt: str,
        additional_context: list[str],
        session: PersistentSession | None = None,
        images: list | None = None,
    ) -> AsyncIterator[str]: ...


@dataclass(frozen=True, slots=True)
class PlannerTurn:
    client: ChatStreamClient
    prompt: str
    additional_context: list[str]
    session: PersistentSession | None = None
    images: list | None = None


AnswerFallback = Callable[[], Awaitable[str]]
StreamFallback = Callable[[], AsyncIterator[str]]


async def planned_or_answered(
    *, studio_turn: PlannerTurn, fallback_turn: AnswerFallback
) -> str:
    chunks: list[str] = []
    yielded_any = False
    try:
        async for chunk in studio_turn.client.chat_stream(
            studio_turn.prompt,
            studio_turn.additional_context,
            studio_turn.session,
            studio_turn.images,
        ):
            if chunk:
                yielded_any = True
            chunks.append(chunk)
    except SubstrateThrottled:
        raise
    except SubstrateCopilotError:
        if yielded_any:
            raise
        if studio_turn.session is not None:
            studio_turn.session.reset_conversation()
        return await fallback_turn()
    return "".join(chunks)


async def planned_or_streamed(
    *, studio_turn: PlannerTurn, fallback_turn: StreamFallback
) -> AsyncIterator[str]:
    yielded_any = False
    try:
        async for chunk in studio_turn.client.chat_stream(
            studio_turn.prompt,
            studio_turn.additional_context,
            studio_turn.session,
            studio_turn.images,
        ):
            if chunk:
                yielded_any = True
            yield chunk
    except SubstrateThrottled:
        raise
    except SubstrateCopilotError:
        if yielded_any:
            raise
        if studio_turn.session is not None:
            studio_turn.session.reset_conversation()
        async for chunk in fallback_turn():
            yield chunk
