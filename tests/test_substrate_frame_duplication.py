from __future__ import annotations

import asyncio
import json

from m365_copilot_openai_proxy import substrate_client
from m365_copilot_openai_proxy.substrate_client import SIGNALR_SEP, SubstrateCopilotClient


# Frame-level reproduction of the "reply shows up twice" bug.
#
# The duplication was a product of frame TIMING, not of any single string: the
# turn streams writeAtCursor deltas, then the t==2 completion frame restates the
# whole answer, and _message_content runs normalize_m365_media_text over that
# restatement while the streamed deltas were only citation-cleaned. The two texts
# therefore diverge even though the model said one thing once.
#
# These tests drive the real _chat_stream_for_turn through a fake SignalR socket
# and let the PRODUCTION normalizer create the divergence, so the scenario is not
# hand-crafted into existence. No token or network needed.

DESIGNER_URL = (
    "https://designerapp.officeapps.live.com/designerapp/document.ashx"
    "?id=abc123&sid=def456"
)
ASYNCGW_URL = (
    "https://apac.asyncgw.teams.microsoft.com/v1/objects/0-eu-d1/views/original/report.py"
)


def _fake_ws(messages: list[dict]):
    """A SignalR WebSocket that replays `messages` then ends the turn (t==3)."""

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, data):
            return None

        async def recv(self):
            return "{}" + SIGNALR_SEP

        def __aiter__(self):
            self._messages = iter(
                [json.dumps(m) + SIGNALR_SEP for m in [*messages, {"type": 3}]]
            )
            return self

        async def __anext__(self):
            try:
                return next(self._messages)
            except StopIteration:
                raise StopAsyncIteration

    return FakeWebSocket


def _client(tone: str = "Magic") -> SubstrateCopilotClient:
    client = SubstrateCopilotClient.__new__(SubstrateCopilotClient)
    client._token = "token"
    client._time_zone = "Asia/Shanghai"
    client._tone = tone
    client._extra_tool_prompt = ""
    client._oid = "oid"
    client._tid = "tid"
    return client


def _delta(text: str) -> dict:
    return {"type": 1, "target": "update", "arguments": [{"writeAtCursor": text}]}


def _complete(text: str) -> dict:
    return {"type": 2, "item": {"messages": [{"author": "bot", "text": text}]}}


def _run(messages: list[dict], monkeypatch) -> str:
    monkeypatch.setattr(
        substrate_client.websockets, "connect", lambda *a, **k: _fake_ws(messages)()
    )

    async def go():
        return [
            chunk
            async for chunk in _client()._chat_stream_for_turn(
                text="go", conv_id="conv", session_id="session", is_start_of_session=True
            )
        ]

    return "".join(asyncio.run(go()))


def test_completion_frame_restating_a_normalized_image_does_not_duplicate(monkeypatch):
    """Normalizer-divergence guard. The turn streams a raw backticked designer
    URL; the completion frame restates the same text, but
    normalize_m365_media_text rewrites the URL into ![image](...) on the way
    through _message_content, so the two texts differ.

    Verified NOT to reproduce the original bug: the pre-fix signature already
    stripped both URL forms to the same thing, so this case passed before too.
    It is kept as a regression guard, because normalizer-driven divergence is
    exactly the class of difference the coverage ratio now has to absorb."""
    answer = f"图表已经做好了。\n\n! `{DESIGNER_URL}`\n\n还需要调整吗？"
    out = _run([_delta("图表已经做好了。\n\n"), _delta(f"! `{DESIGNER_URL}`\n\n"),
                _delta("还需要调整吗？"), _complete(answer)], monkeypatch)

    assert out.count("图表已经做好了。") == 1
    assert out.count("还需要调整吗？") == 1


def test_completion_frame_restating_an_asyncgw_link_does_not_duplicate(monkeypatch):
    """Same shape via the other normalizer branch: a backticked asyncgw media URL
    becomes a [下载 <name>](url) link in the fallback only. Also passed pre-fix;
    kept for the same regression reason as the designer-URL case above."""
    answer = f"脚本在这里：`{ASYNCGW_URL}`  下载后直接运行。"
    out = _run([_delta("脚本在这里："), _delta(f"`{ASYNCGW_URL}`  下载后直接运行。"),
                _complete(answer)], monkeypatch)

    assert out.count("脚本在这里") == 1
    assert out.count("下载后直接运行") == 1


def test_completion_frame_rewording_one_clause_does_not_duplicate(monkeypatch):
    """THE reproduction: this is the case that actually failed before the fix.

    M365 re-words the final frame -- here a single swapped punctuation mark.
    That defeats startswith, containment and the signature-subset test alike, so
    the old code fell through to `return fallback_text` and the whole answer was
    emitted twice. Only the coverage ratio catches it. Confirmed to fail against
    the pre-fix _final_fallback_remainder."""
    streamed = ["第一步安装依赖。", "第二步运行迁移。", "第三步启动服务。"]
    out = _run([_delta(d) for d in streamed]
               + [_complete("第一步安装依赖。第二步运行迁移！第三步启动服务。")], monkeypatch)

    assert out.count("第一步安装依赖") == 1
    assert out.count("第三步启动服务") == 1


def test_completion_frame_carrying_a_real_tail_still_delivers_it(monkeypatch):
    """The counterweight: when the completion frame genuinely holds content the
    stream never sent, that tail must still arrive. A dedupe that swallows it
    would trade a visible bug for a silent one."""
    out = _run([_delta("开头部分。"),
                _complete("开头部分。这一段结尾只在完成帧里出现，必须发出来。")], monkeypatch)

    assert out.count("开头部分。") == 1
    assert "这一段结尾只在完成帧里出现，必须发出来。" in out


def test_stream_without_completion_restatement_is_untouched(monkeypatch):
    """No fallback divergence at all: plain deltas pass through verbatim,
    including a repeated token that per-delta dedupe must not eat."""
    out = _run([_delta("2a_1"), _delta(" + 3d = 6\n"), _delta("2a_1"), _delta(" + 7d = 10\n")],
               monkeypatch)

    assert out == "2a_1 + 3d = 6\n2a_1 + 7d = 10\n"
