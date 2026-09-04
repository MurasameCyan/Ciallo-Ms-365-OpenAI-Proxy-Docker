"""ConsumerClientAdapter contract: flattens prompt+context like the substrate
client, drops the substrate-only session while forwarding images to the consumer
client's own upload path, and re-raises upstream failures as
SubstrateCopilotError so the /v1 route error mapping is unchanged."""

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
        self.images = []

    async def chat_stream(self, prompt, conversation_id="", images=None):
        self.prompts.append((prompt, conversation_id))
        self.images.append(images)
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


def test_adapter_caps_long_prompt_and_keeps_current_turn_head_and_tail():
    adapter = ConsumerClientAdapter(FakeConsumerClient(), max_prompt_chars=320)
    current = "CURRENT_HEAD:" + ("x" * 700) + ":CURRENT_TAIL"

    _collect(adapter.chat_stream(current, additional_context=["old context" * 100]))

    (prompt, _) = adapter._client.prompts[0]
    assert len(prompt) <= 320
    assert "CURRENT_HEAD:" in prompt
    assert ":CURRENT_TAIL" in prompt
    assert "old context" not in prompt


def test_adapter_keeps_latest_tool_result_before_old_history_and_system():
    adapter = ConsumerClientAdapter(FakeConsumerClient(), max_prompt_chars=700)
    transcript = (
        "Prior conversation transcript:\n"
        "OLD_HISTORY_SENTINEL\n"
        + ("history " * 500)
        + "\nTool: Tool result\nLATEST_TOOL_RESULT_SENTINEL"
    )
    system = "System instructions:\nSYSTEM_HEAD\n" + ("rules " * 400) + "\nSYSTEM_TAIL"

    _collect(
        adapter.chat_stream(
            "CURRENT_USER_SENTINEL",
            additional_context=[system, transcript],
        )
    )

    (prompt, _) = adapter._client.prompts[0]
    assert len(prompt) <= 700
    assert "CURRENT_USER_SENTINEL" in prompt
    assert "LATEST_TOOL_RESULT_SENTINEL" in prompt
    assert "OLD_HISTORY_SENTINEL" not in prompt


def test_adapter_keeps_recent_history_before_latest_tool_result():
    adapter = ConsumerClientAdapter(FakeConsumerClient(), max_prompt_chars=360)
    transcript = (
        "Prior conversation transcript:\n"
        + ("old " * 300)
        + "\nRECENT_CONTEXT_SENTINEL\n"
        + "Tool: Tool result\nLATEST_TOOL_RESULT_SENTINEL"
    )

    _collect(
        adapter.chat_stream(
            "CURRENT_USER_SENTINEL",
            additional_context=[transcript],
        )
    )

    (prompt, _) = adapter._client.prompts[0]
    assert prompt.index("RECENT_CONTEXT_SENTINEL") < prompt.index(
        "LATEST_TOOL_RESULT_SENTINEL"
    )


def test_adapter_preserves_compact_tool_contract_without_m365_format_duplication():
    adapter = ConsumerClientAdapter(FakeConsumerClient(), max_prompt_chars=500)
    contract = (
        "Consumer tool contract:\n"
        "Emit a tool_call JSON request.\n"
        "- Read(file_path: string required)\n"
        "- Write(file_path: string required, content: string required)"
    )

    _collect(adapter.chat_stream("CURRENT", additional_context=[contract]))

    (prompt, _) = adapter._client.prompts[0]
    assert contract in prompt
    assert "[FORMAT]" not in prompt
    assert len(prompt) <= 500


def test_adapter_rejects_contract_that_would_truncate_short_current_turn():
    adapter = ConsumerClientAdapter(FakeConsumerClient(), max_prompt_chars=320)
    contract = "Consumer tool contract:\n" + ("x" * 270)

    with pytest.raises(
        ValueError,
        match="Consumer prompt exceeds 320-character budget",
    ):
        _collect(
            adapter.chat_stream(
                "CURRENT_USER_SENTINEL",
                additional_context=[contract],
            )
        )

    assert adapter._client.prompts == []


def test_adapter_rejects_contract_that_leaves_no_room_for_long_current_turn():
    max_chars = 320
    prefix = "Consumer tool contract:\n"
    contract = prefix + ("x" * (max_chars - 7 - len(prefix)))
    adapter = ConsumerClientAdapter(FakeConsumerClient(), max_prompt_chars=max_chars)

    with pytest.raises(
        ValueError,
        match="required tool signatures and current user prompt",
    ):
        _collect(adapter.chat_stream("y" * 1000, additional_context=[contract]))

    assert adapter._client.prompts == []


def test_adapter_counts_unicode_characters_not_utf8_bytes():
    adapter = ConsumerClientAdapter(FakeConsumerClient(), max_prompt_chars=240)

    _collect(adapter.chat_stream("开头" + ("你" * 500) + "结尾"))

    (prompt, _) = adapter._client.prompts[0]
    assert len(prompt) <= 240
    assert prompt.startswith("开头")
    assert prompt.endswith("结尾")


def test_adapter_drops_the_session_but_hands_images_to_the_consumer_client():
    """``session`` is a substrate-only handle and means nothing here, while images
    must survive the seam: the consumer client uploads them itself
    (`/c/api/attachments`). Swallowing them here is what made every consumer
    model answer picture turns blind."""
    adapter = ConsumerClientAdapter(FakeConsumerClient())
    images = [{"mime": "image/png"}]

    _collect(adapter.chat_stream("hi", session={"id": 1}, images=images))

    (prompt, conv_id) = adapter._client.prompts[0]
    assert conv_id == ""
    assert prompt == "hi"
    assert adapter._client.images == [images]


def test_adapter_forwards_images_on_the_non_stream_path_too():
    adapter = ConsumerClientAdapter(FakeConsumerClient())
    images = [{"mime": "image/png"}]

    async def _once():
        return await adapter.chat("hi", None, None, images)

    assert asyncio.run(_once()) == "hello world"
    assert adapter._client.images == [images]


def test_adapter_passes_no_images_as_none_rather_than_inventing_a_list():
    adapter = ConsumerClientAdapter(FakeConsumerClient())

    _collect(adapter.chat_stream("hi"))

    assert adapter._client.images == [None]


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
