"""Tool calling must not fail silently on a tone that ignores the contract.

Measured 2026-08-18: only the Claude Sonnet tones honour the injected
``tool_call`` contract. Every Copilot/GPT tone answers in prose instead -- so a
client that sent ``tools`` got an ordinary answer, HTTP 200 and no signal at all,
which is indistinguishable from a broken proxy. The pipeline is fine; the tone is
the variable, and nothing said so.

Three surfaces are pinned here:
  * ``/v1/models`` advertises the measured status, so the mismatch is avoidable.
  * a tools-bearing turn that produced nothing on a known-bad tone carries a
    readable note, on both the buffered and the streaming path.
  * ``tool_choice=required``/named with zero tool_calls is a hard 400 -- the one
    case where prose provably cannot satisfy the request. ``auto`` stays 200,
    because a prose answer is legitimate there and hard-failing it would break
    plain chats that merely carry a ``tools`` array.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_api_chat import _openai_stream_with_tools
from m365_copilot_openai_proxy.routes_api_common import (
    REQUIRED_NO_CALL_OUTCOME,
    REQUIRED_REJECTED_CALL_OUTCOME,
    TOOL_CALLING_HEADER,
    TOOL_OUTCOME_HEADER,
    build_consumer_models_list,
    required_tool_call_error,
    tool_calling_note,
)
from m365_copilot_openai_proxy.tone_options import tone_tool_calling
from m365_copilot_openai_proxy.tone_resolver import build_models_list

# Models: display labels, since that is how a client addresses a tone.
UNSUPPORTED_MODEL = "Copilot_自动"          # tone Magic, measured 0/3
VERIFIED_MODEL = "claude-sonnet-4-6"        # tone Claude_Sonnet, measured 3/3
UNKNOWN_MODEL = "gpt-5.2"                   # tone Gpt_5_2_Reasoning, never measured

PROSE = "我无法访问你本地的文件，请把文件作为附件上传。"
FENCED = '```tool_call\n{"name": "Read", "arguments": {"file_path": "/tmp/a.txt"}}\n```'

READ_TOOL = {"type": "function", "function": {"name": "Read", "description": "Read a file"}}
A_READ_TOOL = {"name": "Read", "description": "Read a file", "input_schema": {"type": "object"}}


def _client(tmp_path, reply: str) -> TestClient:
    class FakeClient:
        _tone = "Magic"

        async def chat(self, prompt, context=None, session=None, images=None):
            return reply

        async def chat_stream(self, prompt, context=None, session=None, images=None):
            yield reply

    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kw: FakeClient(),
    )
    # This file is about the native contract and the measured map, so the router is
    # pinned off: under the shipped default ("auto") a measured-broken tone is
    # routed instead, and those paths belong to test_tool_router.py.
    app.state.tool_planning_mode = "native"
    return TestClient(app)


def _chat(client: TestClient, model: str, reply_tools=(READ_TOOL,), **extra):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "读一下 /tmp/a.txt"}],
        **extra,
    }
    if reply_tools is not None:
        body["tools"] = list(reply_tools)
    return client.post("/v1/chat/completions", json=body, headers={"Authorization": "Bearer k"})


def _messages(client: TestClient, model: str, **extra):
    body = {
        "model": model,
        "max_tokens": 512,
        "messages": [{"role": "user", "content": "读一下 /tmp/a.txt"}],
        "tools": [A_READ_TOOL],
        **extra,
    }
    return client.post("/v1/messages", json=body, headers={"x-api-key": "k"})


# --- the measured map ---------------------------------------------------------

@pytest.mark.parametrize(
    "tone,expected",
    [
        ("Claude_Sonnet", "verified"),
        ("Claude_Sonnet_Reasoning", "verified"),
        ("Magic", "unsupported"),
        ("Gpt_5_5_Chat", "unsupported"),
        ("Gpt_5_2_Reasoning", "unknown"),   # never measured -> never flagged
        ("SomeFutureTone", "unknown"),
        (None, "unknown"),
    ],
)
def test_tone_tool_calling_status(tone, expected):
    assert tone_tool_calling(tone) == expected


# --- /v1/models advertises it -------------------------------------------------

def test_models_list_marks_tool_calling_per_tone():
    entries = {
        entry["id"]: entry
        for entry in build_models_list(
            [
                {"value": "Magic", "label": "Copilot_自动"},
                {"value": "Claude_Sonnet", "label": "claude-sonnet-4-6"},
                {"value": "Gpt_5_2_Reasoning", "label": "gpt-5.2"},
            ],
            created=0,
            planning_mode="native",
        )
    }

    assert entries["Copilot_自动"]["tool_calling"] == "unsupported"
    assert entries["Copilot_自动"]["capabilities"]["tools"] is False
    assert entries["claude-sonnet-4-6"]["tool_calling"] == "verified"
    assert entries["claude-sonnet-4-6"]["capabilities"]["tools"] is True
    # Unmeasured tones must not be advertised as broken.
    assert entries["gpt-5.2"]["tool_calling"] == "unknown"
    assert entries["gpt-5.2"]["capabilities"]["tools"] is True
    # The persistent variant carries the same status as its base tone.
    assert entries["Copilot_自动-持续"]["tool_calling"] == "unsupported"
    # Pre-existing hints stay put.
    assert entries["Copilot_自动"]["capabilities"]["vision"] is True


def test_models_route_exposes_tool_calling(tmp_path):
    data = _client(tmp_path, PROSE).get(
        "/v1/models", headers={"Authorization": "Bearer k"}
    ).json()["data"]
    assert {entry["tool_calling"] for entry in data} <= {"verified", "unsupported", "unknown"}
    assert any(entry["tool_calling"] == "verified" for entry in data)


# --- auto: loud but not fatal -------------------------------------------------

def test_unsupported_tone_note_reaches_the_client(tmp_path):
    r = _chat(_client(tmp_path, PROSE), UNSUPPORTED_MODEL)

    assert r.status_code == 200
    assert r.headers[TOOL_CALLING_HEADER] == "unsupported"
    content = r.json()["choices"][0]["message"]["content"]
    assert PROSE in content, "the model's own answer must still be delivered"
    assert "不支持本地工具调用" in content
    assert VERIFIED_MODEL in content, "the note must name a model that does work"


def test_unsupported_tone_note_absent_when_tool_calls_did_arrive(tmp_path):
    # Reality outranks the map: if the tone complied, say nothing.
    r = _chat(_client(tmp_path, FENCED), UNSUPPORTED_MODEL)

    assert r.status_code == 200
    choice = r.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert "不支持本地工具调用" not in (choice["message"].get("content") or "")


def test_plain_chat_without_tools_is_untouched(tmp_path):
    r = _chat(_client(tmp_path, PROSE), UNSUPPORTED_MODEL, reply_tools=None)

    assert r.status_code == 200
    assert TOOL_CALLING_HEADER not in r.headers
    assert r.json()["choices"][0]["message"]["content"] == PROSE


def test_tool_choice_none_is_untouched(tmp_path):
    # "none" empties the effective tool list, so there is no shortfall to report.
    r = _chat(_client(tmp_path, PROSE), UNSUPPORTED_MODEL, tool_choice="none")

    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == PROSE


def test_unmeasured_tone_gets_no_note(tmp_path):
    r = _chat(_client(tmp_path, PROSE), UNKNOWN_MODEL)

    assert r.status_code == 200
    assert r.headers[TOOL_CALLING_HEADER] == "unknown"
    assert r.json()["choices"][0]["message"]["content"] == PROSE


def test_verified_tone_gets_no_note(tmp_path):
    r = _chat(_client(tmp_path, PROSE), VERIFIED_MODEL)

    assert r.status_code == 200
    assert r.headers[TOOL_CALLING_HEADER] == "verified"
    assert r.json()["choices"][0]["message"]["content"] == PROSE


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "model,expected",
    [
        (UNSUPPORTED_MODEL, "router"),
        (UNKNOWN_MODEL, "unknown"),
        (VERIFIED_MODEL, "verified"),
    ],
)
def test_auto_header_keeps_effective_tool_calling_status(
    stream, model, expected, tmp_path
):
    client = _client(tmp_path, PROSE)
    client.app.state.tool_planning_mode = "auto"

    r = _chat(client, model, stream=stream)

    assert r.status_code == 200
    assert r.headers[TOOL_CALLING_HEADER] == expected


# --- required/named: hard failure --------------------------------------------

@pytest.mark.parametrize(
    ("tool_choice", "expected_outcome"),
    [
        ("required", REQUIRED_NO_CALL_OUTCOME),
        ({"type": "function", "function": {"name": "Read"}}, None),
    ],
)
def test_demanded_tool_call_that_never_came_is_a_400(
    tmp_path, tool_choice, expected_outcome
):
    r = _chat(_client(tmp_path, PROSE), UNSUPPORTED_MODEL, tool_choice=tool_choice)

    assert r.status_code == 400
    assert r.headers.get(TOOL_OUTCOME_HEADER) == expected_outcome
    detail = r.json()["error"]["message"]
    assert "Magic" in detail                  # names the tone actually used
    assert UNSUPPORTED_MODEL in detail        # and the model the client asked for
    assert VERIFIED_MODEL in detail           # and a way out


def test_demanded_tool_call_is_enforced_on_verified_tones_too(tmp_path):
    # Outcome-gated, not map-gated: a verified tone that answered in prose still
    # failed to satisfy the request, and no retry can fix a wrong tool_choice.
    r = _chat(_client(tmp_path, PROSE), VERIFIED_MODEL, tool_choice="required")
    assert r.status_code == 400


def test_demanded_tool_call_that_did_arrive_is_fine(tmp_path):
    r = _chat(_client(tmp_path, FENCED), UNSUPPORTED_MODEL, tool_choice="required")

    assert r.status_code == 200
    assert r.json()["choices"][0]["finish_reason"] == "tool_calls"


def test_required_outcome_header_requires_a_nonempty_tool_list(tmp_path):
    r = _chat(
        _client(tmp_path, PROSE),
        VERIFIED_MODEL,
        reply_tools=(),
        tool_choice="required",
    )

    assert r.status_code == 400
    assert TOOL_OUTCOME_HEADER not in r.headers


def test_read_only_guard_is_exempt_from_the_hard_failure(tmp_path):
    # Dropping a mutating call is our own policy, not an upstream shortfall, so it
    # must not be reported as one.
    client = _client(
        tmp_path,
        '```tool_call\n{"name": "Write", "arguments": {"file_path": "/tmp/a", "content": "x"}}\n```',
    )
    body = {
        "model": UNSUPPORTED_MODEL,
        "messages": [{"role": "user", "content": "只读一下就好，不要修改任何文件"}],
        "tools": [{"type": "function", "function": {"name": "Write", "description": "w"}}],
        "tool_choice": "required",
    }
    r = client.post("/v1/chat/completions", json=body, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200


# --- streaming ---------------------------------------------------------------

def _joined_content(sse: str) -> str:
    out = ""
    for line in sse.splitlines():
        if line.startswith("data: ") and line[6:] != "[DONE]":
            payload = json.loads(line[6:])
            for choice in payload.get("choices", []):
                out += choice.get("delta", {}).get("content", "")
    return out


def test_stream_with_tools_appends_the_note(tmp_path):
    class _Prose:
        async def chat_stream(self, prompt, context=None, session=None, images=None):
            yield PROSE

    async def run() -> list[str]:
        return [
            frame
            async for frame in _openai_stream_with_tools(
                "m365-model", _Prose(), "hi", [], None,
                tool_names={"Read"}, shortfall_note="⚠️ 测试提示：不支持本地工具调用",
            )
        ]

    content = _joined_content("".join(asyncio.run(run())))
    assert PROSE in content
    assert "不支持本地工具调用" in content


def test_stream_with_tools_omits_the_note_when_tool_calls_arrived(tmp_path):
    class _Fenced:
        async def chat_stream(self, prompt, context=None, session=None, images=None):
            yield FENCED

    async def run() -> list[str]:
        return [
            frame
            async for frame in _openai_stream_with_tools(
                "m365-model", _Fenced(), "hi", [], None,
                tool_names={"Read"}, shortfall_note="⚠️ 测试提示：不支持本地工具调用",
            )
        ]

    frames = asyncio.run(run())
    assert "不支持本地工具调用" not in _joined_content("".join(frames))
    assert '"finish_reason": "tool_calls"' in "".join(frames)


def test_stream_route_sets_the_header(tmp_path):
    with _client(tmp_path, PROSE).stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": UNSUPPORTED_MODEL,
            "stream": True,
            "messages": [{"role": "user", "content": "读一下"}],
            "tools": [READ_TOOL],
        },
        headers={"Authorization": "Bearer k"},
    ) as r:
        assert r.headers[TOOL_CALLING_HEADER] == "unsupported"
        body = "".join(chunk for chunk in r.iter_text())
    # SSE payloads are json.dumps'd with ensure_ascii, so decode before matching.
    assert "不支持本地工具调用" in _joined_content(body)


def test_streamed_demanded_tool_call_is_reported_as_readable_text(tmp_path):
    # A stream cannot answer 400: its headers went out before the turn was even
    # buffered. The demanded-call failure has to arrive as content instead, or the
    # client is back to staring at prose it cannot use.
    r = _chat(
        _client(tmp_path, PROSE), UNSUPPORTED_MODEL, stream=True, tool_choice="required"
    )

    assert r.status_code == 200
    content = _joined_content(r.text)
    assert "tool_choice=required" in content
    assert "没有产出任何" in content
    assert VERIFIED_MODEL in content


def test_streamed_demanded_tool_call_that_arrived_says_nothing(tmp_path):
    r = _chat(
        _client(tmp_path, FENCED), UNSUPPORTED_MODEL, stream=True, tool_choice="required"
    )

    assert r.status_code == 200
    assert "tool_choice=required" not in r.text
    assert '"finish_reason": "tool_calls"' in r.text


# --- the note's own precedence ------------------------------------------------

def test_demanded_note_outranks_the_advisory_note(tmp_path):
    # Both apply on an unsupported tone under tool_choice=required. Only the
    # stronger one is delivered -- it already names the tone and the way out.
    content = _joined_content(
        _chat(
            _client(tmp_path, PROSE), UNSUPPORTED_MODEL,
            stream=True, tool_choice="required",
        ).text
    )
    assert "不支持本地工具调用" not in content


def test_read_only_guard_streams_no_note_at_all(tmp_path):
    # Our own policy dropped the call, so there is no upstream shortfall to report.
    client = _client(
        tmp_path,
        '```tool_call\n{"name": "Write", "arguments": {"file_path": "/tmp/a", "content": "x"}}\n```',
    )
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": UNSUPPORTED_MODEL,
            "stream": True,
            "tool_choice": "required",
            "messages": [{"role": "user", "content": "只读一下就好，不要修改任何文件"}],
            "tools": [{"type": "function", "function": {"name": "Write", "description": "w"}}],
        },
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 200
    assert "没有产出任何" not in _joined_content(r.text)


# --- the Anthropic shape, which is what Claude Code actually speaks ----------

def test_anthropic_unsupported_tone_note_reaches_the_client(tmp_path):
    r = _messages(_client(tmp_path, PROSE), UNSUPPORTED_MODEL)

    assert r.status_code == 200
    assert r.headers[TOOL_CALLING_HEADER] == "unsupported"
    text = "".join(b.get("text", "") for b in r.json()["content"])
    assert PROSE in text
    assert "不支持本地工具调用" in text


def test_anthropic_demanded_tool_call_that_never_came_is_a_400(tmp_path):
    r = _messages(_client(tmp_path, PROSE), UNSUPPORTED_MODEL, tool_choice={"type": "any"})

    assert r.status_code == 400
    assert VERIFIED_MODEL in r.json()["error"]["message"]


def test_anthropic_tool_use_that_did_arrive_is_fine(tmp_path):
    r = _messages(_client(tmp_path, FENCED), UNSUPPORTED_MODEL, tool_choice={"type": "any"})

    assert r.status_code == 200
    assert r.json()["stop_reason"] == "tool_use"


def test_anthropic_streamed_demanded_tool_call_is_readable_text(tmp_path):
    r = _messages(
        _client(tmp_path, PROSE), UNSUPPORTED_MODEL,
        stream=True, tool_choice={"type": "any"},
    )

    assert r.status_code == 200
    text = ""
    for line in r.text.splitlines():
        if line.startswith("data: "):
            delta = json.loads(line[6:]).get("delta") or {}
            text += delta.get("text", "")
    assert "没有产出任何" in text
    assert VERIFIED_MODEL in text


# --- admin: the operator's own view ------------------------------------------

def test_admin_tone_annotates_without_storing(tmp_path):
    client = _client(tmp_path, PROSE)
    assert client.post("/admin/login", json={"password": "k"}).status_code == 200

    options = client.get("/admin/tone").json()["options"]

    statuses = {o["value"]: o["tool_calling"] for o in options}
    assert statuses["Claude_Sonnet"] == "verified"
    # _client pins planning to "native", where nothing covers a measured-broken tone.
    assert statuses["Magic"] == "unsupported"
    # Measured status is not a setting: it must never leak into the editable list
    # that /admin/runtime-settings persists.
    assert all("tool_calling" not in o for o in client.app.state.tone_options)

    client.app.state.tool_planning_mode = "auto"
    routed = client.get("/admin/tone").json()["options"]

    # Effective, like /v1/models: under the shipped default the same tone is routed
    # and does produce calls, so the picker must not keep calling it unsupported.
    assert {o["value"]: o["tool_calling"] for o in routed}["Magic"] == "router"


def test_admin_tone_picker_marks_measured_tones_by_colour(tmp_path):
    from m365_copilot_openai_proxy.template_admin_settings_js import _ADMIN_SETTINGS_JS
    from m365_copilot_openai_proxy.template_admin_i18n import _ADMIN_I18N_JS
    from m365_copilot_openai_proxy.template_assets import _GLASS_SELECT_CSS, _GLASS_SELECT_JS

    # One tooltip per measured status, so an unmarked mode means "not measured" and
    # never "measured fine".
    assert (
        "TIPS={verified:'tc_tip_verified',router:'tc_tip_router',"
        "flaky:'tc_tip_flaky',unsupported:'tc_tip_unsupported'}"
    ) in _ADMIN_SETTINGS_JS
    assert "op.dataset.tc=o.tool_calling" in _ADMIN_SETTINGS_JS
    for tip in ("tc_tip_verified", "tc_tip_router", "tc_tip_flaky", "tc_tip_unsupported"):
        assert _ADMIN_I18N_JS.count(tip + ":") == 2, tip  # zh + en
    # The status has to survive the glass select, which paints its own trigger and
    # menu: a colour needs an element of its own, and the tooltip has to ride along
    # because a hue alone is not a signal every operator can read.
    assert "s.className='tc-mark'" in _GLASS_SELECT_JS
    assert "el.title=(o&&o.title)||''" in _GLASS_SELECT_JS
    # Green / amber / red, with amber shared by "routed" and "flaky" -- both mean
    # "you get calls, but not from the mode's own native compliance".
    assert '.tc-mark[data-tc="verified"]{color:#22c55e}' in _GLASS_SELECT_CSS
    assert '.tc-mark[data-tc="router"],.tc-mark[data-tc="flaky"]{color:#f59e0b}' in _GLASS_SELECT_CSS
    assert '.tc-mark[data-tc="unsupported"]{color:#ef4444}' in _GLASS_SELECT_CSS
    # A colour-emoji wrench ignores `color`, so the glyph must ask for text
    # presentation -- U+FE0E plus the CSS property that backs it up.
    assert "🔧︎" in _GLASS_SELECT_JS
    assert "font-variant-emoji:text" in _GLASS_SELECT_CSS


def test_call_log_shows_a_degraded_tools_turn():
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
    from m365_copilot_openai_proxy.template_admin_i18n import _ADMIN_I18N_JS

    assert "l.tool_calling==='unsupported'" in _ADMIN_HTML
    # flaky is its own line: the follow-up is "retry", not "switch models".
    assert "l.tool_calling==='flaky'" in _ADMIN_HTML
    assert "tool_calling: " in _ADMIN_HTML          # and in the copyable record
    assert _ADMIN_I18N_JS.count("tool_calling_unsupported:") == 2  # zh + en
    assert _ADMIN_I18N_JS.count("tool_calling_flaky:") == 2


def test_call_log_shows_a_dropped_or_declined_tools_turn():
    """The two new outcomes have to be visible where an operator diagnoses a
    "tools are broken" report, not only in the response body."""
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
    from m365_copilot_openai_proxy.template_admin_i18n import _ADMIN_I18N_JS

    assert "l.tool_calls_rejected" in _ADMIN_HTML
    assert "l.tool_declined" in _ADMIN_HTML
    assert _ADMIN_I18N_JS.count("tool_calls_rejected:") == 2
    assert _ADMIN_I18N_JS.count("tool_declined:") == 2


def test_call_log_records_the_status(tmp_path):
    client = _client(tmp_path, PROSE)
    _chat(client, UNSUPPORTED_MODEL)

    record = client.app.state.call_log[-1]
    assert record["tool_calling"] == "unsupported"
    assert record["tool_calls_result"] == []


def test_call_log_omits_the_status_without_tools(tmp_path):
    client = _client(tmp_path, PROSE)
    _chat(client, UNSUPPORTED_MODEL, reply_tools=None)

    assert "tool_calling" not in client.app.state.call_log[-1]


# --- NO_TOOL_NEEDED: "I decided not to" is not the same as "I ignored you" -----
#
# Absence of tool_calls alone conflates a correct no-action turn with a tone that
# never honoured the contract, and the two need opposite advice ("your request
# needed no tool" vs "switch models"). The explicit token, borrowed from
# HEXUXIU/M365-Copilot2API's router prompt, is what tells them apart.

ANSWER = "4"
DECLINED = f"{ANSWER}\n\nNO_TOOL_NEEDED"


def test_the_contract_asks_for_the_token(tmp_path):
    """The parser is useless if the prompt never requests the token. Pinned because
    the two live in different modules and only fail together at runtime."""
    from m365_copilot_openai_proxy.models import OpenAIChatRequest
    from m365_copilot_openai_proxy.translator import translate_openai_request

    translated = translate_openai_request(
        OpenAIChatRequest(
            model=UNSUPPORTED_MODEL,
            messages=[{"role": "user", "content": "2+2"}],
            tools=[READ_TOOL],
        )
    )

    assert "NO_TOOL_NEEDED" in "\n".join(translated.additional_context)


def test_declined_turn_is_delivered_clean_and_unblamed(tmp_path):
    r = _chat(_client(tmp_path, DECLINED), UNSUPPORTED_MODEL)

    assert r.status_code == 200
    content = r.json()["choices"][0]["message"]["content"]
    assert ANSWER in content
    # The token is protocol chatter -- the user must never see it.
    assert "NO_TOOL_NEEDED" not in content
    # ...and the tone honoured the contract, so the "doesn't support tools" note
    # would be a lie even though this tone is on the measured-bad list.
    assert "不支持本地工具调用" not in content


def test_declined_turn_is_recorded_for_the_operator(tmp_path):
    client = _client(tmp_path, DECLINED)
    _chat(client, UNSUPPORTED_MODEL)

    assert client.app.state.call_log[-1]["tool_declined"] is True


def test_declined_changes_the_demanded_failure_diagnosis(tmp_path):
    """Still a 400 -- the demanded call is still missing -- but blaming the tone
    here would send the caller to change models over a working turn."""
    r = _chat(_client(tmp_path, DECLINED), UNSUPPORTED_MODEL, tool_choice="required")

    assert r.status_code == 400
    message = r.json()["error"]["message"]
    assert "NO_TOOL_NEEDED" in message
    assert "重试不会改变结果" not in message


def test_the_token_alone_is_treated_as_a_malformed_turn(tmp_path):
    """A reply that is *only* the token answered the protocol instead of the user.
    Reporting that as a deliberate no-action turn would hide a real failure."""
    r = _chat(_client(tmp_path, "NO_TOOL_NEEDED"), UNSUPPORTED_MODEL)

    assert r.status_code == 200
    assert "不支持本地工具调用" in r.json()["choices"][0]["message"]["content"]


def test_declined_turn_is_not_turned_into_a_synthesized_write(tmp_path):
    """The prose-Write fallback and the corrective retry both exist to rescue a
    turn that *meant* to act. A turn that said it would not act must not be
    rescued into writing a file."""
    reply = f"Saved to `C:/temp/a.py`\n\n```python\nx=1\n```\n\nNO_TOOL_NEEDED"
    write_tool = {"type": "function", "function": {"name": "Write"}}

    r = _chat(_client(tmp_path, reply), UNSUPPORTED_MODEL, reply_tools=(write_tool,))

    assert r.status_code == 200
    assert r.json()["choices"][0]["finish_reason"] == "stop"


def test_streamed_declined_turn_is_stripped_and_unblamed(tmp_path):
    r = _chat(_client(tmp_path, DECLINED), UNSUPPORTED_MODEL, stream=True)

    content = _joined_content(r.text)
    assert ANSWER in content
    assert "NO_TOOL_NEEDED" not in content
    assert "不支持本地工具调用" not in content


def test_anthropic_declined_turn_is_stripped_and_unblamed(tmp_path):
    r = _messages(_client(tmp_path, DECLINED), UNSUPPORTED_MODEL)

    assert r.status_code == 200
    text = "".join(b.get("text", "") for b in r.json()["content"])
    assert ANSWER in text
    assert "NO_TOOL_NEEDED" not in text
    assert "不支持本地工具调用" not in text


# --- argument schemas: don't forward a call the client cannot execute ----------
#
# tool_calls here are *parsed out of prose*, so wrong names and missing required
# arguments are routine. Forwarding one moves the failure to the client, where it
# reads as a client-side validation bug with no hint that the model got it wrong.

SCHEMA = {
    "type": "object",
    "properties": {"file_path": {"type": "string"}},
    "required": ["file_path"],
}
READ_TOOL_SCHEMA = {
    "type": "function",
    "function": {"name": "Read", "description": "Read a file", "parameters": SCHEMA},
}
A_READ_TOOL_SCHEMA = {"name": "Read", "description": "Read a file", "input_schema": SCHEMA}
FENCED_MISSING_ARG = '```tool_call\n{"name": "Read", "arguments": {"pathx": "/tmp/a.txt"}}\n```'
FENCED_UNKNOWN_TOOL = '```tool_call\n{"name": "Delete", "arguments": {"file_path": "/tmp/a.txt"}}\n```'


def test_a_valid_call_still_reaches_the_client(tmp_path):
    r = _chat(_client(tmp_path, FENCED), VERIFIED_MODEL, reply_tools=(READ_TOOL_SCHEMA,))

    assert r.status_code == 200
    assert r.json()["choices"][0]["finish_reason"] == "tool_calls"


def test_a_call_missing_a_required_argument_is_dropped_and_reported(tmp_path):
    client = _client(tmp_path, FENCED_MISSING_ARG)
    r = _chat(client, VERIFIED_MODEL, reply_tools=(READ_TOOL_SCHEMA,))

    assert r.status_code == 200
    assert r.json()["choices"][0]["finish_reason"] == "stop"
    content = r.json()["choices"][0]["message"]["content"]
    assert "不符合客户端声明的工具定义" in content
    assert "file_path" in content
    assert client.app.state.call_log[-1]["tool_calls_rejected"]


def test_a_call_for_a_tool_that_was_never_offered_is_dropped(tmp_path):
    r = _chat(_client(tmp_path, FENCED_UNKNOWN_TOOL), VERIFIED_MODEL, reply_tools=(READ_TOOL_SCHEMA,))

    assert r.status_code == 200
    content = r.json()["choices"][0]["message"]["content"]
    assert "Delete" in content and "Read" in content


def test_a_schema_we_cannot_compile_never_blocks_a_call(tmp_path):
    """Our own uncertainty is not the model's fault: rejecting here would break
    tool calling for any client whose schema we merely failed to resolve."""
    broken = {
        "type": "function",
        "function": {"name": "Read", "parameters": {"$ref": "#/$defs/missing"}},
    }

    r = _chat(_client(tmp_path, FENCED), VERIFIED_MODEL, reply_tools=(broken,))

    assert r.json()["choices"][0]["finish_reason"] == "tool_calls"


def test_a_dropped_call_under_required_is_a_400_naming_the_reason(tmp_path):
    r = _chat(
        _client(tmp_path, FENCED_MISSING_ARG), VERIFIED_MODEL,
        reply_tools=(READ_TOOL_SCHEMA,), tool_choice="required",
    )

    assert r.status_code == 400
    assert r.headers[TOOL_OUTCOME_HEADER] == REQUIRED_REJECTED_CALL_OUTCOME
    assert "file_path" in r.json()["error"]["message"]


def test_streamed_dropped_call_is_reported_as_readable_text(tmp_path):
    r = _chat(
        _client(tmp_path, FENCED_MISSING_ARG), VERIFIED_MODEL,
        reply_tools=(READ_TOOL_SCHEMA,), stream=True,
    )

    content = _joined_content(r.text)
    assert "不符合客户端声明的工具定义" in content
    assert "tool_calls" not in r.text


def test_anthropic_call_violating_input_schema_is_dropped(tmp_path):
    r = _messages(
        _client(tmp_path, FENCED_MISSING_ARG), VERIFIED_MODEL, tools=[A_READ_TOOL_SCHEMA],
    )

    assert r.status_code == 200
    assert r.json()["stop_reason"] == "end_turn"
    text = "".join(b.get("text", "") for b in r.json()["content"])
    assert "不符合客户端声明的工具定义" in text



# --- the Consumer half of the map ---------------------------------------------

@pytest.mark.parametrize(
    "mode,expected",
    [
        ("search", "verified"),      # 3/3
        ("research", "verified"),    # 3/3
        ("reasoning", "verified"),   # 5/6, the one miss recorded in the table
        ("smart", "flaky"),          # 1/6 -- provably capable, not reliable
        ("chat", "flaky"),           # 1/3
        ("study", "unsupported"),    # 0/3
        ("computer_use", "unknown"), # never measured -> never flagged
    ],
)
def test_consumer_mode_tool_calling_status(mode, expected):
    assert tone_tool_calling(mode) == expected


def test_consumer_models_list_advertises_the_measured_status(tmp_path):
    entries = {
        entry["id"]: entry
        for entry in build_consumer_models_list(
            [
                {"model": "copilot-study", "mode": "study", "status": "experimental"},
                {"model": "copilot-search", "mode": "search", "status": "experimental"},
                {"model": "copilot", "mode": "smart", "status": "stable"},
            ],
            created=0,
            planning_mode="native",
        )
    }

    assert entries["copilot-study"]["tool_calling"] == "unsupported"
    assert entries["copilot-study"]["capabilities"]["tools"] is False
    assert entries["copilot-search"]["capabilities"]["tools"] is True
    # Flaky can still produce calls, so withholding tools would be the wrong advice.
    assert entries["copilot"]["capabilities"]["tools"] is True
    # And under the shipped default the router plans those turns, so the honest
    # answer to "will tools work here" becomes yes.
    routed = build_consumer_models_list(
        [{"model": "copilot-study", "mode": "study", "status": "experimental"}], created=0,
    )
    assert routed[0]["tool_calling"] == "router"
    assert routed[0]["capabilities"]["tools"] is True


def test_a_flaky_selector_says_retrying_may_help_and_names_reachable_models(tmp_path):
    """A Consumer key cannot address a tone, so the note must not recommend one."""
    app = _client(tmp_path, PROSE).app

    note = tool_calling_note(app, "copilot", "smart", 1)

    assert "不稳定" in note and "重试" in note
    assert "copilot-search" in note
    assert VERIFIED_MODEL not in note, "a Consumer key is rejected for asking about a tone"


def test_an_empty_tools_turn_says_the_upstream_returned_nothing(tmp_path):
    """Measured live: a flaky Consumer mode can answer with no text at all, and a
    note claiming "上面返回的是普通回复" would then be pointing at nothing."""
    from m365_copilot_openai_proxy.routes_api_common import prose_with_reason

    app = _client(tmp_path, PROSE).app
    note = tool_calling_note(app, "copilot", "smart", 1)

    assert "上面" not in note, "the note itself must not claim there is prose above it"
    assert prose_with_reason("", shortfall_note=note).startswith("⚠️ 上游本轮没有返回任何文字。")
    assert prose_with_reason("answer", shortfall_note=note) == f"answer\n\n{note}"


def test_a_routed_turn_is_never_told_its_model_is_unreliable(tmp_path):
    """Observed live 2026-08-19 under the default ``auto``: a routed turn whose
    router declined in its own words instead of the marker got the flaky note,
    i.e. "switch models" advice about the shape that did not plan the turn."""
    app = _client(tmp_path, PROSE).app

    for mode in ("router", "auto"):
        note = tool_calling_note(app, "copilot", "smart", 1, mode)
        assert "工具路由器" in note, mode
        assert "不稳定" not in note and "copilot-search" not in note, mode
    # The selector auto leaves on the native path still gets the native wording.
    assert tool_calling_note(app, "copilot-search", "search", 1, "auto") == ""
    assert "不稳定" in tool_calling_note(app, "copilot", "smart", 1, "native")


def test_a_routed_turn_that_owes_a_call_blames_the_router_not_the_tone(tmp_path):
    app = _client(tmp_path, PROSE).app

    routed = required_tool_call_error(
        app,
        model_str="copilot",
        tone="smart",
        choice=("required", None, False),
        tool_calls=[],
        read_only_guard=False,
        planning_mode="auto",
    )

    assert "路由器" in routed
    assert "copilot-search" not in routed, "under routing every selector can call"


# --- router mode changes what /v1/models may claim ----------------------------

def test_models_list_reports_router_when_the_router_plans_the_turn(tmp_path):
    entries = {
        entry["id"]: entry
        for entry in build_models_list(
            [
                {"value": "Magic", "label": "Copilot_自动"},
                {"value": "Claude_Sonnet", "label": "claude-sonnet-4-6"},
            ],
            created=0,
            planning_mode="router",
        )
    }

    # Pessimism is a lie here: with the router planning the turn, sending tools to
    # Magic really does produce calls, and a client gating on this would withhold them.
    assert entries["Copilot_自动"]["tool_calling"] == "router"
    assert entries["Copilot_自动"]["capabilities"]["tools"] is True
    assert entries["claude-sonnet-4-6"]["tool_calling"] == "verified"
