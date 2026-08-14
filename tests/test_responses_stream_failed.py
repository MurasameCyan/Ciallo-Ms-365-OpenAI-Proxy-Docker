from __future__ import annotations

import asyncio

from m365_copilot_openai_proxy.response_helpers import _responses_stream
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotError


def _collect(gen_factory):
    async def run():
        return [chunk async for chunk in gen_factory()]

    return asyncio.run(run())


def test_responses_stream_emits_response_failed_envelope_on_upstream_error():
    """On upstream failure the Responses stream must emit BOTH the out-of-band
    ``error`` event (kept for existing clients) and the semantic
    ``response.failed`` terminal envelope. Responses API has no ``[DONE]``
    sentinel; ``response.failed`` is what lets strict clients (e.g. Codex) stop
    cleanly instead of hanging for more deltas. See OpenAI Responses streaming
    spec."""

    class FailingStreamClient:
        async def chat_stream(self, prompt, additional_context, session=None, images=None):
            raise SubstrateCopilotError("upstream broke")
            yield ""  # unreachable; marks this as an async generator

    chunks = _collect(
        lambda: _responses_stream("m365-copilot", FailingStreamClient(), "hi", [])
    )
    body = "".join(chunks)

    # Both events present.
    assert '"type": "error"' in body
    assert '"type": "response.failed"' in body
    # Envelope is well-formed and carries a stable error code + failed status.
    assert '"status": "failed"' in body
    assert '"code": "server_error"' in body
    assert '"message": "upstream broke"' in body
    # response.failed is the terminal event: it comes after the error event and
    # a successful response.completed is NOT emitted on the failure path.
    assert body.index('"type": "error"') < body.index('"type": "response.failed"')
    assert '"type": "response.completed"' not in body


def test_responses_stream_emits_response_completed_on_success():
    """Regression guard: the happy path still terminates with response.completed
    (and never response.failed), so adding the failure envelope did not disturb
    the success terminal event."""

    class OkStreamClient:
        async def chat_stream(self, prompt, additional_context, session=None, images=None):
            yield "hello"

    chunks = _collect(
        lambda: _responses_stream("m365-copilot", OkStreamClient(), "hi", [])
    )
    body = "".join(chunks)

    assert '"type": "response.completed"' in body
    assert '"type": "response.failed"' not in body
    assert '"type": "error"' not in body
