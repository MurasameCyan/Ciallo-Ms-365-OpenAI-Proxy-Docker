from __future__ import annotations

import asyncio
import json

from m365_copilot_openai_proxy.response_helpers import (
    _anthropic_stream,
    _openai_stream,
    _responses_stream,
)


def _collect(gen_factory):
    async def run():
        return [chunk async for chunk in gen_factory()]

    return asyncio.run(run())


# chat_stream already yields a deduplicated, incremental delta stream (the
# t==3 fallback reconciliation happens INSIDE substrate_client). Each delta the
# stream forwards is genuinely-new content and must be emitted verbatim. Math
# and code answers repeat short tokens across separate deltas -- e.g. "2a_1",
# "+ 3d = 6", closing "}" -- so a per-delta dedup that drops any delta whose
# text already appeared earlier corrupts formulas (\frac{8}{2}(2a_1+7d) losing
# 2a_1) and silently deletes code. These guards feed repeated tokens and assert
# nothing is dropped.

class _RepeatClient:
    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        for d in ["2a_1", " + 3d = 6\n", "2a_1", " + 7d = 10\n"]:
            yield d


def _openai_content(body: str) -> str:
    out = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload.strip() == "[DONE]":
            continue
        obj = json.loads(payload)
        for choice in obj.get("choices", []):
            piece = choice.get("delta", {}).get("content")
            if piece:
                out.append(piece)
    return "".join(out)


def test_openai_stream_preserves_repeated_token_deltas():
    body = "".join(_collect(lambda: _openai_stream("m365-copilot", _RepeatClient(), "hi", [])))
    assert _openai_content(body) == "2a_1 + 3d = 6\n2a_1 + 7d = 10\n"


def test_responses_stream_preserves_repeated_token_deltas():
    body = "".join(_collect(lambda: _responses_stream("m365-copilot", _RepeatClient(), "hi", [])))
    deltas = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        obj = json.loads(line[len("data: "):])
        if obj.get("type") == "response.output_text.delta":
            deltas.append(obj.get("delta", ""))
    assert "".join(deltas) == "2a_1 + 3d = 6\n2a_1 + 7d = 10\n"


def test_anthropic_stream_preserves_repeated_token_deltas():
    body = "".join(_collect(lambda: _anthropic_stream("m365-copilot", _RepeatClient(), "hi", [])))
    deltas = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        obj = json.loads(line[len("data: "):])
        if obj.get("type") == "content_block_delta":
            deltas.append(obj.get("delta", {}).get("text", ""))
    assert "".join(deltas) == "2a_1 + 3d = 6\n2a_1 + 7d = 10\n"
