from __future__ import annotations

import asyncio
import json

from m365_copilot_openai_proxy.media_proxy import rewrite_m365_media_urls
from m365_copilot_openai_proxy.routes_api_messages import _anthropic_stream_with_tools
from m365_copilot_openai_proxy.tool_call_parser import _looks_like_fake_file_claim


# Found against a live deployment: asked for a file, M365 used its NATIVE file
# generation (hosted the file on asyncgw and answered with a download link)
# instead of emitting a tool_call. The corrective retry that exists for exactly
# this case never fired, because the media rewriter had already run: it
# base64-encodes the source URL into a ?u= parameter, which erases the ".py"
# suffix _looks_like_fake_file_claim keys on. Parsing must therefore see the RAW
# model text, with rewriting deferred to delivery.

ASYNCGW_FILE_URL = (
    "https://jp-prod.asyncgw.teams.microsoft.com/v1/objects/"
    "0-ea-d11-7aa079db7a471418e3154dc6c20ed3c1/views/original/demo.py"
)
NATIVE_FILE_REPLY = f"[demo.py]({ASYNCGW_FILE_URL})"


def _rewriter(text: str) -> str:
    # allowed_suffixes gates FILE extensions, not hosts; ".py" is in the default
    # set, so the default is what production uses here.
    return rewrite_m365_media_urls(
        text,
        base_url="https://proxy.example",
        account_id="acct_1",
        secret="secret",
    )


def test_media_rewrite_destroys_the_fake_file_claim_signal():
    """Pins the mechanism, so the ordering requirement is self-documenting."""
    rewritten = _rewriter(NATIVE_FILE_REPLY)

    assert rewritten != NATIVE_FILE_REPLY, "rewriter did not fire; test is vacuous"
    assert _looks_like_fake_file_claim(NATIVE_FILE_REPLY) is True
    assert _looks_like_fake_file_claim(rewritten) is False


class _NativeThenToolCallClient:
    """First turn answers with a hosted file link; the retry emits a real tool_call."""

    def __init__(self):
        self.prompts: list[str] = []

    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            yield NATIVE_FILE_REPLY
        else:
            yield (
                "```tool_call\n"
                '{"name": "Write", "arguments": {"file_path": "S:/tmp/demo.py",'
                ' "content": "print(1)"}}\n'
                "```"
            )


def _events(gen) -> list[dict]:
    async def run():
        return [chunk async for chunk in gen]

    out = []
    for chunk in asyncio.run(run()):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def test_corrective_retry_fires_even_with_a_media_rewriter_attached():
    """End-to-end: with the rewriter attached, the native-file-gen reply must
    still trigger the retry and yield a real tool_use block."""
    client = _NativeThenToolCallClient()
    call_record: dict = {}

    events = _events(_anthropic_stream_with_tools(
        "m365-copilot",
        client,
        "在 S:/tmp/demo.py 写一个文件",
        [],
        call_record=call_record,
        tool_names={"Write"},
        text_transform=_rewriter,
    ))

    assert len(client.prompts) == 2, "corrective retry did not fire"
    assert call_record.get("retried") is True
    kinds = [e["content_block"]["type"] for e in events
             if e.get("type") == "content_block_start"]
    assert "tool_use" in kinds
    assert call_record["tool_calls_result"] == ["Write"]


def test_delivered_prose_is_still_media_rewritten():
    """Deferring the rewrite must not drop it: prose that reaches the client is
    still rewritten, and the raw URL never leaks."""

    class _ProseClient:
        async def chat_stream(self, prompt, additional_context, session=None, images=None):
            yield f"文件在这里：{ASYNCGW_FILE_URL}"

    events = _events(_anthropic_stream_with_tools(
        "m365-copilot", _ProseClient(), "给我文件", [],
        tool_names={"Write"}, text_transform=_rewriter,
    ))
    text = "".join(e["delta"]["text"] for e in events
                   if e.get("type") == "content_block_delta"
                   and e["delta"].get("type") == "text_delta")

    assert "文件在这里" in text
    assert ASYNCGW_FILE_URL not in text
    assert "/v1/m365-media?" in text


def test_write_tool_call_content_is_not_touched_by_the_rewriter():
    """A Write payload carrying a media URL must reach the host byte-for-byte:
    rewriting it would corrupt the file that gets written."""

    class _WriteWithUrlClient:
        async def chat_stream(self, prompt, additional_context, session=None, images=None):
            yield (
                "```tool_call\n"
                + json.dumps({
                    "name": "Write",
                    "arguments": {
                        "file_path": "S:/tmp/links.md",
                        "content": f"see {ASYNCGW_FILE_URL}",
                    },
                }, ensure_ascii=False)
                + "\n```"
            )

    events = _events(_anthropic_stream_with_tools(
        "m365-copilot", _WriteWithUrlClient(), "写下这个链接", [],
        tool_names={"Write"}, text_transform=_rewriter,
    ))
    payload = next(e["delta"]["partial_json"] for e in events
                   if e.get("type") == "content_block_delta"
                   and e["delta"].get("type") == "input_json_delta")

    assert json.loads(payload)["content"] == f"see {ASYNCGW_FILE_URL}"
