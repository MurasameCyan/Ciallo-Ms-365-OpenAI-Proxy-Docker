"""Adapt the consumer-Copilot client to the Substrate client's route contract.

Every /v1 route calls one shape -- ``chat_stream(prompt, additional_context,
session, images)`` / ``chat(...)`` -- and catches ``SubstrateCopilotError``,
mapping it to a status code via ``upstream_http_error``. Consumer Copilot speaks
a different protocol (``ConsumerCopilotClient.chat_stream(prompt,
conversation_id)``) and raises ``ConsumerCopilotError``. This wrapper is the
single seam between them, so the routes need no per-provider branching:

* It flattens ``prompt`` + ``additional_context`` exactly the way
  ``SubstrateCopilotClient`` does (shared ``_combine_text``), which also gives
  consumer accounts the same prompt-simulated tool-call instructions for free.
* It drops the substrate-only ``session`` and ``images`` arguments. Consumer is
  a stateless text bridge: the full transcript is re-sent as ``additional_context``
  every turn, so a fresh conversation per turn loses no context.
* It re-raises upstream failures as ``SubstrateCopilotError`` so the existing
  route error mapping keeps working unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .consumer_client import ConsumerCopilotClient, ConsumerCopilotError
from .substrate_client import SubstrateCopilotError
from .substrate_parse import _combine_text


class ConsumerClientAdapter:
    """Present a ``ConsumerCopilotClient`` through the Substrate route contract."""

    def __init__(self, client: ConsumerCopilotClient):
        self._client = client

    async def chat_stream(
        self,
        prompt: str,
        additional_context: list[str] | None = None,
        session=None,
        images=None,
    ) -> AsyncIterator[str]:
        # ponytail: images are dropped -- the consumer bridge is text-only. Ceiling:
        # a request carrying an image gets a text-only answer. Upgrade path: port
        # the browser's image-upload handshake into ConsumerCopilotClient.
        text = _combine_text(prompt, additional_context or [])
        try:
            async for chunk in self._client.chat_stream(text):
                yield chunk
        except ConsumerCopilotError as exc:
            # Collapses ClearanceRequired/RegionBlocked too: the routes only know
            # SubstrateCopilotError, and upstream_http_error keys on marker
            # strings, so a consumer clearance/region failure surfaces as a 502
            # carrying its own message -- which is the correct operator signal.
            raise SubstrateCopilotError(str(exc)) from exc

    async def chat(
        self,
        prompt: str,
        additional_context: list[str] | None = None,
        session=None,
        images=None,
    ) -> str:
        return "".join(
            [chunk async for chunk in self.chat_stream(prompt, additional_context, session, images)]
        )
