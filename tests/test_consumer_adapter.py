"""ConsumerClientAdapter contract: flattens prompt+context like the substrate
client, drops substrate-only session/images, and re-raises upstream failures
as SubstrateCopilotError so the /v1 route error mapping is unchanged."""

from __future__ import annotations

import asyncio

import pytest

from m365_copilot_openai_proxy.consumer_adapter import ConsumerClientAdapter
from m365_copilot_openai_proxy.consumer_client import AccountThrottled, ConsumerCopilotError
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotError


class FakeConsumerClient:
    def __init__(self, chunks=("hello", " world"), fail=None):
        self._chunks = chunks
        self._fail = fail
        self.prompts = []

    async def chat_stream(self, prompt, conversation_id=""):
        self.prompts.append((prompt, conversation_id))
        if self._fail:
            raise self._fail
        for chunk in self._chunks:
            yield chunk


def _collect(stream):
    async def _drain():
        return [chunk async for chunk in stream]

    return asyncio.run(_drain())


def test_adapter_flattens_prompt_and_context_like_substrate():
    adapter = ConsumerClientAdapter(FakeConsumerClient())
    chunks = _collect(adapter.chat_stream("answer", additional_context=["ctx-a", "ctx-b"]))
    assert "".join(chunks) == "hello world"
    (prompt, conv_id) = adapter._client.prompts[0]
    assert conv_id == ""
    assert prompt == "ctx-a\n\nctx-b\n\n---\n\nanswer"


def test_adapter_drops_session_and_images_arguments():
    adapter = ConsumerClientAdapter(FakeConsumerClient())
    _collect(adapter.chat_stream("hi", session={"id": 1}, images=[{"mime": "image/png"}]))
    (prompt, conv_id) = adapter._client.prompts[0]
    assert conv_id == ""
    assert prompt == "hi"


def test_adapter_reraises_stable_consumer_error_unchanged():
    adapter = ConsumerClientAdapter(FakeConsumerClient(fail=ConsumerCopilotError("boom")))
    adapter.mode_status = "stable"
    try:
        _collect(adapter.chat_stream("hi"))
    except SubstrateCopilotError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected SubstrateCopilotError")


def test_adapter_preserves_account_throttle_metadata():
    adapter = ConsumerClientAdapter(
        FakeConsumerClient(
            fail=AccountThrottled(
                "quota", "2026-08-13T15:17:13+00:00"
            )
        )
    )
    with pytest.raises(SubstrateCopilotError) as error:
        _collect(adapter.chat_stream("hi"))
    assert isinstance(error.value.__cause__, AccountThrottled)
    assert error.value.next_available_at == "2026-08-13T15:17:13+00:00"


def test_adapter_appends_rollout_hint_to_experimental_consumer_error():
    adapter = ConsumerClientAdapter(FakeConsumerClient(fail=ConsumerCopilotError("boom")))
    adapter.mode_status = "experimental"
    try:
        _collect(adapter.chat_stream("hi"))
    except SubstrateCopilotError as exc:
        assert str(exc).startswith("boom")
        assert str(exc).endswith(
            "该实验 mode 可能受账户、地区或 Microsoft rollout 限制"
        )
    else:
        raise AssertionError("expected SubstrateCopilotError")
