from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.media_proxy import rewrite_m365_media_urls
from m365_copilot_openai_proxy.routes_api_messages import _anthropic_stream_with_tools
from m365_copilot_openai_proxy.tool_call_parser import (
    _looks_like_fake_file_claim,
    planner_fallback_needed,
)


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


# An image reply is the other half of the same detector: the phrase branch keys on
# 已生成/生成了, which is exactly how both providers word an image turn ("已生成一张
# 图片：![...]"). The image is a real artifact, so the claim is not fake -- but the
# retry fired anyway, spending a second upstream turn (on consumer, another image
# quota unit) and, when that turn produced a Write call, replacing the delivered
# image with it. That is the reported symptom: it says the picture is ready and
# there is no picture.
CAT_DATA_URI = "data:image/jpeg;base64,/9j/4AAQSkZJRg"
CONSUMER_IMAGE_REPLY = f"已生成一张图片：\n\n![一只猫]({CAT_DATA_URI})\n\n"
M365_IMAGE_REPLY = (
    "已生成图片：\n\n"
    "![cat](https://proxy.example/v1/m365-media?account_id=acct_1&u=aHR0cA&exp=1&sig=x)"
)
# What the M365 routes actually hand the predicate: rewriting is deferred to
# delivery, so upstream's own shape is still there -- a backticked host url, not
# markdown. Keying "delivered image" on markdown alone therefore protected only
# the consumer side; on M365 已生成图片 still scored as a fake file claim.
DESIGNER_IMAGE_URL = (
    "https://designerapp.officeapps.live.com/designerapp/document.ashx"
    "?path=%2Fdalle-9f1c.png&fileToken=tok"
)
ASYNCGW_IMAGE_URL = (
    "https://jp-prod.asyncgw.teams.microsoft.com/v1/objects/"
    "0-ea-d4-101412848fe8be7ad7f1c4c110d1fa4f/views/original/cat.png"
)
M365_RAW_IMAGE_REPLY = f"已生成图片：\n\n !`{DESIGNER_IMAGE_URL}` \n\n"
WRITE_TOOL = {"type": "function", "function": {"name": "Write", "description": "Write a file"}}
WRITE_TOOL_ANTHROPIC = {
    "name": "Write",
    "description": "Write a file",
    "input_schema": {"type": "object"},
}


def test_a_delivered_image_is_not_a_fake_file_claim():
    assert _looks_like_fake_file_claim(CONSUMER_IMAGE_REPLY) is False
    assert _looks_like_fake_file_claim(M365_IMAGE_REPLY) is False
    # Without an image the same prose still has to trigger the retry, and a
    # hosted code-file link still counts even when an image sits beside it:
    # that link is direct evidence, the phrase is only circumstantial.
    assert _looks_like_fake_file_claim("已生成 demo.py，见附件") is True
    assert _looks_like_fake_file_claim(
        f"已生成两个文件\n\n![cat]({CAT_DATA_URI})\n\n{NATIVE_FILE_REPLY}"
    ) is True


def test_a_delivered_image_does_not_escalate_to_another_planner():
    # The planner chain asks the same question a different way, and it used to
    # stop on the fake-file-claim verdict. Without this the fix above would only
    # move the wasted turn from the corrective retry to the next planner, which
    # cannot produce a tool_call for an image either.
    assert planner_fallback_needed(CONSUMER_IMAGE_REPLY, {"Write"}) is False
    assert planner_fallback_needed(M365_RAW_IMAGE_REPLY, {"Write"}) is False
    # Prose with no calls must still escalate, or the chain is dead.
    assert planner_fallback_needed("我无法访问你本地的文件。", {"Write"}) is True


def test_a_delivered_image_is_recognised_in_its_raw_upstream_shape():
    """The M365 half of the exemption, in the shape the routes really see.

    Both call sites parse the RAW text on purpose, with the media rewriter
    deferred to delivery, so a delivered M365 image is upstream's backticked or
    bare host url. Markdown-only recognition left every M365 image turn carrying
    tools exposed to the corrective retry.
    """
    assert _looks_like_fake_file_claim(M365_RAW_IMAGE_REPLY) is False
    assert _looks_like_fake_file_claim(f"已生成图片：\n\n `{ASYNCGW_IMAGE_URL}` ") is False
    assert _looks_like_fake_file_claim(f"已生成图片 {ASYNCGW_IMAGE_URL}") is False
    # An already-signed url can come back in through conversation history.
    assert _looks_like_fake_file_claim(M365_IMAGE_REPLY) is False


def test_markdown_pointing_at_a_bare_path_is_still_a_fake_claim():
    """The exemption must not cover a claim with nothing behind it.

    No inline bytes, no host to fetch from: the model says it wrote a file and
    did not, which is the whole reason the corrective retry exists.
    """
    assert _looks_like_fake_file_claim(
        "已生成图表并保存为 chart.png：\n\n![chart](chart.png)"
    ) is True
    assert _looks_like_fake_file_claim("已生成 ![out](S:/tmp/out.png)") is True


class _ImageThenToolCallClient:
    """An image turn worded 已生成; a retry, if one fires, answers with a Write."""

    def __init__(self, reply=CONSUMER_IMAGE_REPLY):
        self.reply = reply
        self.prompts: list[str] = []

    async def chat(self, prompt, additional_context=None, session=None, images=None):
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            return self.reply
        return (
            "```tool_call\n"
            '{"name": "Write", "arguments": {"file_path": "S:/tmp/cat.png",'
            ' "content": "not the image"}}\n'
            "```"
        )

    async def chat_stream(self, prompt, additional_context=None, session=None, images=None):
        yield await self.chat(prompt, additional_context, session, images)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "reply,markers",
    [
        (CONSUMER_IMAGE_REPLY, (CAT_DATA_URI,)),
        (M365_RAW_IMAGE_REPLY, ("document.ashx", "/v1/m365-media?")),
    ],
    ids=["consumer-data-uri", "m365-raw-backtick"],
)
def test_an_image_turn_carrying_tools_delivers_the_image_and_spends_one_turn(
    tmp_path, stream, reply, markers
):
    """The reported symptom, at the surface a client sees: a tools-bearing image
    request must come back with the image, not with a Write call for a .png the
    model would have to invent, and must not cost a second upstream turn.

    Both directions, because each buffers the whole turn and then runs its own
    copy of `full_text, tool_calls = retry_text, retry_calls`. Both provider
    shapes, because the M365 one reaches the predicate as a raw host url and the
    consumer one as an inline data uri. Whether that host url then arrives raw or
    signed is the media rewriter's business (pinned in tests/test_media_proxy.py);
    here the only claim is that the image survived the tools path.
    """
    upstream = _ImageThenToolCallClient(reply)
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kw: upstream,
    )
    # No planner chain: this is about the corrective retry, not routing.
    app.state.tool_planning_mode = "native"

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer k"},
        json={
            "model": "m365-copilot",
            "messages": [{"role": "user", "content": "画一只猫"}],
            "tools": [WRITE_TOOL],
            "stream": stream,
        },
    )

    assert response.status_code == 200
    if stream:
        deltas = [
            json.loads(line[6:])["choices"][0]["delta"]
            for line in response.text.splitlines()
            if line.startswith("data: ") and line[6:].strip() != "[DONE]"
        ]
        content = "".join(d.get("content") or "" for d in deltas)
        assert any(marker in content for marker in markers), content
        assert not [d for d in deltas if d.get("tool_calls")]
    else:
        message = response.json()["choices"][0]["message"]
        content = message.get("content") or ""
        assert any(marker in content for marker in markers), content
        assert not message.get("tool_calls")
    assert len(upstream.prompts) == 1, "a corrective retry spent a second image turn"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "reply,markers",
    [
        (CONSUMER_IMAGE_REPLY, (CAT_DATA_URI,)),
        (M365_RAW_IMAGE_REPLY, ("document.ashx", "/v1/m365-media?")),
    ],
    ids=["consumer-data-uri", "m365-raw-backtick"],
)
def test_an_image_turn_carrying_tools_survives_the_anthropic_surface_too(
    tmp_path, stream, reply, markers
):
    """Same guard on /v1/messages, which is what Claude Code speaks.

    routes_api_messages keeps its own copy of the retry application in each
    direction (:545 non-stream, :752 stream), so the OpenAI-surface tests above
    do not cover it -- only the predicate is shared.
    """
    upstream = _ImageThenToolCallClient(reply)
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kw: upstream,
    )
    app.state.tool_planning_mode = "native"

    response = TestClient(app).post(
        "/v1/messages",
        headers={"x-api-key": "k"},
        json={
            "model": "m365-copilot",
            "max_tokens": 512,
            "messages": [{"role": "user", "content": "画一只猫"}],
            "tools": [WRITE_TOOL_ANTHROPIC],
            "stream": stream,
        },
    )

    assert response.status_code == 200
    if stream:
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and line[6:].strip() != "[DONE]"
        ]
        content = "".join(
            e["delta"].get("text") or ""
            for e in events
            if e.get("type") == "content_block_delta"
            and e.get("delta", {}).get("type") == "text_delta"
        )
        started = [
            e["content_block"]["type"]
            for e in events
            if e.get("type") == "content_block_start"
        ]
        assert "tool_use" not in started, started
    else:
        blocks = response.json()["content"]
        content = "".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
        assert not [b for b in blocks if b.get("type") == "tool_use"], blocks
    assert any(marker in content for marker in markers), content
    assert len(upstream.prompts) == 1, "a corrective retry spent a second image turn"
