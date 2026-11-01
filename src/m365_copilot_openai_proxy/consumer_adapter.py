"""Adapt the consumer-Copilot client to the Substrate client's route contract.

Every /v1 route calls one shape -- ``chat_stream(prompt, additional_context,
session, images)`` / ``chat(...)`` -- and catches ``SubstrateCopilotError``,
mapping it to a status code via ``upstream_http_error``. Consumer Copilot speaks
a different protocol (``ConsumerCopilotClient.chat_stream(prompt,
conversation_id)``) and raises ``ConsumerCopilotError``. This wrapper is the
single seam between them, so the routes need no per-provider branching:

* It preserves the shared ``_combine_text`` result while it fits, then compacts
  only Consumer prompts that exceed the configured upstream character budget.
  Consumer tool requests carry a dedicated compact prompt contract.
* It forwards ``images`` -- Consumer uploads them itself (``/c/api/attachments``)
  rather than through the M365 upload path -- and drops the substrate-only
  ``session`` argument. Consumer is stateless: the full transcript is re-sent as
  ``additional_context`` every turn, so a fresh conversation per turn loses no
  context.
* It preserves quota and network failures as typed ``SubstrateCopilotError``
  subclasses so both streaming and HTTP route error mapping keep working.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .consumer_client import AccountThrottled, ConsumerCopilotClient, ConsumerCopilotError, ConsumerNetworkError
from .consumer_prompt import compact_consumer_prompt
from .sse_stream import closing_stream
from .substrate_client import SubstrateCopilotError, SubstrateNetworkError, SubstrateThrottled
from .substrate_parse import _combine_text


_EXPERIMENTAL_MODE_HINT = (
    "该实验 mode 可能受账户、地区或 Microsoft rollout 限制"
)


class ConsumerClientAdapter:
    """Present a ``ConsumerCopilotClient`` through the Substrate route contract."""

    def __init__(self, client: ConsumerCopilotClient, max_prompt_chars: int = 8000):
        self._client = client
        self.max_prompt_chars = max_prompt_chars
        self.mode_status = "stable"

    @property
    def mode(self) -> str:
        return self._client.mode

    @mode.setter
    def mode(self, value: str) -> None:
        self._client.mode = value

    async def chat_stream(
        self,
        prompt: str,
        additional_context: list[str] | None = None,
        session=None,
        images=None,
    ) -> AsyncIterator[str]:
        context = additional_context or []
        if any(part.startswith("Consumer tool contract:") for part in context):
            text = compact_consumer_prompt(prompt, context, self.max_prompt_chars)
        else:
            text = _combine_text(prompt, context)
            if len(text) > self.max_prompt_chars:
                text = compact_consumer_prompt(prompt, context, self.max_prompt_chars)
        try:
            async with closing_stream(self._client.chat_stream(text, images=images)) as owned_stream:
                async for chunk in owned_stream:
                    yield chunk
        except ConsumerCopilotError as exc:
            # Preserve transport classification; clearance and region refusals
            # remain upstream errors rather than pretending to be network faults.
            detail = str(exc)
            if self.mode_status == "experimental" and not isinstance(exc, ConsumerNetworkError):
                detail = f"{detail}；{_EXPERIMENTAL_MODE_HINT}"
            if isinstance(exc, AccountThrottled):
                translated = SubstrateThrottled(detail)
            elif isinstance(exc, ConsumerNetworkError):
                translated = SubstrateNetworkError(detail)
            else:
                translated = SubstrateCopilotError(detail)
            # Keep the reset timestamp across the route-contract adapter. The
            # HTTP layer uses it to return a useful Retry-After instead of
            # treating an account quota refusal as a generic 502.
            if hasattr(exc, "next_available_at"):
                translated.next_available_at = exc.next_available_at
            raise translated from exc

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
