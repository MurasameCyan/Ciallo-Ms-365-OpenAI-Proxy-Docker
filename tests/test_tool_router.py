"""Router mode: plan the tool turn with a classification prompt, not an inline block.

Measured 2026-08-18, the injected fenced-block contract is honoured only by the
Claude Sonnet tones. Measured again 2026-08-19, a single-purpose "does this turn
need a tool" prompt is honoured by all 7 tones, 16/16 in both directions -- so the
failure was the shape we asked for, not the tone.

What is pinned here is the wiring, not the upstream behaviour: the router decision
is rewritten into the very fenced block the native parser already consumes, so the
schema check, the read-only guard, tool_calls emission and the call log must all
apply to a router-produced call with no router-specific code of their own. Plus the
two ways it must not make things worse: it costs no extra turn on tones that do
honour the native contract, and a failed classification turn falls back to an
ordinary answer instead of failing the request.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.substrate_client import SubstrateCopilotError
from m365_copilot_openai_proxy.tool_call_parser import _extract_tool_calls
from m365_copilot_openai_proxy.tool_call_parser import planner_fallback_needed
from m365_copilot_openai_proxy.tool_router import (
    build_router_prompt,
    parse_router_decision,
    routed_or_answered,
    routed_or_streamed,
    router_applies,
    router_text,
    tool_planning_mode,
)

UNSUPPORTED_MODEL = "Copilot_自动"          # tone Magic, ignores the native contract
VERIFIED_MODEL = "claude-sonnet-4-6"        # tone Claude_Sonnet, honours it

PROSE = "我无法访问你本地的文件，请把文件作为附件上传。"
DECISION = 'CALL_TOOL: Read({"file_path": "/tmp/a.txt"})'

READ_TOOL = {
    "type": "function",
    "function": {
        "name": "Read",
        "description": "Read a file",
        "parameters": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
}
WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "Write",
        "description": "Write a file",
        "parameters": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["file_path", "content"],
        },
    },
}
A_READ_TOOL = {
    "name": "Read",
    "description": "Read a file",
    "input_schema": {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
    },
}

ROUTER_MARKER = "You are a tool-use router"


class FakeClient:
    """Answers the router turn and the ordinary turn differently, and records both.

    The whole point of router mode is that these two prompts get different replies
    out of the same tone, so a fake that cannot tell them apart proves nothing.
    """

    def __init__(self, decision: str, answer: str, fail_router: bool = False):
        self.decision = decision
        self.answer = answer
        self.fail_router = fail_router
        self.turns: list[tuple[str, bool]] = []   # (prompt, had_session)

    def _reply(self, prompt: str, session) -> str:
        routed = ROUTER_MARKER in prompt
        self.turns.append((prompt, session is not None))
        if routed and self.fail_router:
            raise SubstrateCopilotError("classification turn blew up")
        return self.decision if routed else self.answer

    async def chat(self, prompt, context=None, session=None, images=None):
        return self._reply(prompt, session)

    async def chat_stream(self, prompt, context=None, session=None, images=None):
        yield self._reply(prompt, session)

    @property
    def router_turns(self) -> list[str]:
        return [p for p, _ in self.turns if ROUTER_MARKER in p]

    @property
    def answer_turns(self) -> list[str]:
        return [p for p, _ in self.turns if ROUTER_MARKER not in p]


def _app(tmp_path, fake: FakeClient, **state):
    app = create_app(
        Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""),
        copilot_client_factory=lambda **kw: fake,
    )
    for key, value in state.items():
        setattr(app.state, key, value)
    return TestClient(app)


def _chat(client: TestClient, model: str, tools=(READ_TOOL,), **extra):
    return client.post(
        "/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "读一下 /tmp/a.txt"}],
            "tools": list(tools),
            **extra,
        },
        headers={"Authorization": "Bearer k"},
    )


# --- when the router is spent -------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (None, "auto"), ("", "auto"), ("  Router ", "router"), ("native", "native"),
    ("nonsense", "auto"),   # an unknown persisted value must not disable planning
])
def test_planning_mode_is_normalized(raw, expected):
    assert tool_planning_mode(raw) == expected


@pytest.mark.parametrize("mode,tone,expected", [
    # auto keys on the measured status, so a tone that starts honouring the native
    # contract stops paying for the extra turn without a code change.
    ("auto", "Magic", True),
    ("auto", "Gpt_5_5_Chat", True),
    ("auto", "Claude_Sonnet", False),
    ("auto", "Gpt_5_2_Reasoning", False),    # unmeasured -> keep today's behaviour
    ("native", "Magic", False),
    ("router", "Claude_Sonnet", True),
    (None, "Magic", True),                   # missing setting behaves as auto
    # Consumer modes share the map. "flaky" routes: 1-in-6 native compliance is
    # not something an agent client can build on.
    ("auto", "smart", True),
    ("auto", "study", True),
    ("auto", "search", False),               # 3/3 native -> no extra turn
    ("native", "smart", False),
])
def test_router_applies_matrix(mode, tone, expected):
    assert router_applies(mode, tone) is expected


# --- reading the decision -----------------------------------------------------

def test_a_decision_becomes_a_tool_call():
    calls = parse_router_decision(DECISION)

    assert [c["function"]["name"] for c in calls] == ["Read"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"file_path": "/tmp/a.txt"}


def test_commentary_after_the_decision_is_not_swallowed():
    """The reasoning tones keep talking past the decision line.

    Upstream's parser locates the arguments with the LAST ")" in the reply, which
    scoops the commentary into the JSON and loses the call entirely.
    """
    calls = parse_router_decision(
        f"{DECISION}\n\nI chose Read because the user asked to read a file (obviously)."
    )

    assert json.loads(calls[0]["function"]["arguments"]) == {"file_path": "/tmp/a.txt"}


def test_a_no_argument_call_is_still_a_decision():
    assert [c["function"]["name"] for c in parse_router_decision("CALL_TOOL: ListDir()")] == ["ListDir"]


@pytest.mark.parametrize("reply", [
    "NO_TOOL_NEEDED",
    "",
    PROSE,
    "CALL_TOOL: Read(",           # truncated mid-call
    "CALL_TOOL: Read(not json)",  # arguments we cannot read
])
def test_undecided_replies_yield_nothing(reply):
    assert parse_router_decision(reply) == []
    assert router_text(reply) == ""


def test_planner_fallback_predicate_accepts_declared_call_and_preserves_decline():
    assert planner_fallback_needed(
        '```tool_call\n{"name":"Read","arguments":{"file_path":"/tmp/a.txt"}}\n```',
        {"Read"},
    ) is False
    assert planner_fallback_needed("NO_TOOL_NEEDED", {"Read"}) is False
    assert planner_fallback_needed("plain answer", {"Read"}) is True
    assert planner_fallback_needed(
        '```tool_call\n{"name":"Write","arguments":{}}\n```',
        {"Read"},
    ) is True


def test_the_decision_is_rewritten_into_the_shape_the_native_parser_reads():
    """This equivalence is what lets every downstream stage stay router-unaware."""
    def shape(calls):
        return [(c["function"]["name"], json.loads(c["function"]["arguments"])) for c in calls]

    assert shape(_extract_tool_calls(router_text(DECISION))) == shape(parse_router_decision(DECISION))


@pytest.mark.parametrize("stream", [False, True])
def test_router_call_observer_fires_only_for_a_classification_call(stream):
    observed: list[str] = []

    async def run(decision: str, answer: str):
        fake = FakeClient(decision, answer)
        if stream:
            return "".join([
                chunk async for chunk in routed_or_streamed(
                    fake,
                    "You are a tool-use router",
                    "ordinary prompt",
                    [],
                    on_router_call=lambda: observed.append("router"),
                )
            ])
        return await routed_or_answered(
            fake,
            "You are a tool-use router",
            "ordinary prompt",
            [],
            on_router_call=lambda: observed.append("router"),
        )

    asyncio.run(run(DECISION, PROSE))
    assert observed == ["router"]

    observed.clear()
    asyncio.run(run(DECLINED, "```tool_call\n{}\n```"))
    assert observed == []


@pytest.mark.parametrize("stream", [False, True])
def test_router_call_observer_failure_never_breaks_the_request(stream):
    def broken_observer():
        raise RuntimeError("observer failed")

    async def run():
        fake = FakeClient(DECISION, PROSE)
        if stream:
            return "".join([
                chunk async for chunk in routed_or_streamed(
                    fake,
                    "You are a tool-use router",
                    "ordinary prompt",
                    [],
                    on_router_call=broken_observer,
                )
            ])
        return await routed_or_answered(
            fake,
            "You are a tool-use router",
            "ordinary prompt",
            [],
            on_router_call=broken_observer,
        )

    assert "```tool_call" in asyncio.run(run())


def test_a_forced_choice_reaches_the_router_prompt():
    required = build_router_prompt("User: hi", ["- Read: read a file"], ("required", None, False))
    named = build_router_prompt("User: hi", ["- Read: read a file"], ("tool", "Read", False))

    assert "requires a tool call" in required and "Never answer NO_TOOL_NEEDED" in required
    assert "requires the tool named Read" in named
    # The tools still read to the model exactly as the native contract renders them.
    assert "- Read: read a file" in required


# --- end to end: the call reaches the client -----------------------------------

def test_router_turns_an_unsupported_tone_into_a_real_tool_call(tmp_path):
    fake = FakeClient(DECISION, PROSE)
    r = _chat(_app(tmp_path, fake), UNSUPPORTED_MODEL)

    assert r.status_code == 200
    message = r.json()["choices"][0]["message"]
    assert [tc["function"]["name"] for tc in message["tool_calls"]] == ["Read"]
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"file_path": "/tmp/a.txt"}
    assert r.json()["choices"][0]["finish_reason"] == "tool_calls"
    # A decided call needs no answer turn: the decision IS the answer.
    assert len(fake.router_turns) == 1 and fake.answer_turns == []
    # The classification turn must stay out of the user's persistent session.
    assert all(had_session is False for _, had_session in fake.turns)


def test_the_router_prompt_carries_the_conversation_and_the_tools(tmp_path):
    fake = FakeClient(DECISION, PROSE)
    _chat(_app(tmp_path, fake), UNSUPPORTED_MODEL)

    prompt = fake.router_turns[0]
    assert "读一下 /tmp/a.txt" in prompt
    assert "- Read: Read a file" in prompt and "file_path" in prompt
    # The native contract must not be along for the ride: it tells the model to
    # answer normally and embed a fenced block, which is what we are replacing.
    assert "tool_call" not in prompt


def test_a_routed_call_is_still_judged_against_the_client_schema(tmp_path):
    """Reuse claim, load-bearing: the schema filter sits downstream of the router."""
    fake = FakeClient('CALL_TOOL: Read({"path": "/tmp/a.txt"})', PROSE)
    r = _chat(_app(tmp_path, fake), UNSUPPORTED_MODEL)

    assert r.status_code == 200
    content = r.json()["choices"][0]["message"]["content"]
    assert r.json()["choices"][0]["message"].get("tool_calls") in (None, [])
    assert "不符合客户端声明的工具定义" in content
    assert "file_path" in content, "the note must name the offending argument"


def test_a_routed_mutating_call_is_still_blocked_by_the_read_only_guard(tmp_path):
    fake = FakeClient(
        'CALL_TOOL: Write({"file_path": "/tmp/a.txt", "content": "x"})', PROSE
    )
    r = _chat(
        _app(tmp_path, fake, run_permission="read_only"),
        UNSUPPORTED_MODEL,
        tools=(READ_TOOL, WRITE_TOOL),
    )

    assert r.status_code == 200
    assert r.json()["choices"][0]["message"].get("tool_calls") in (None, [])


def test_a_routed_turn_is_labelled_in_the_call_log(tmp_path):
    fake = FakeClient(DECISION, PROSE)
    client = _app(tmp_path, fake)
    _chat(client, UNSUPPORTED_MODEL)

    record = client.app.state.call_log[-1]
    assert record["tool_planning"] == "router"
    assert record["tool_calls_result"] == ["Read"]


def test_streamed_routed_call_reaches_the_client(tmp_path):
    fake = FakeClient(DECISION, PROSE)
    r = _chat(_app(tmp_path, fake), UNSUPPORTED_MODEL, stream=True)

    names = [
        tc["function"]["name"]
        for line in r.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
        for tc in (json.loads(line[6:])["choices"][0]["delta"].get("tool_calls") or [])
        if tc.get("function", {}).get("name")
    ]
    assert names == ["Read"]
    assert fake.answer_turns == []


def test_anthropic_routed_call_becomes_a_tool_use_block(tmp_path):
    fake = FakeClient(DECISION, PROSE)
    r = _app(tmp_path, fake).post(
        "/v1/messages",
        json={
            "model": UNSUPPORTED_MODEL,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": "读一下 /tmp/a.txt"}],
            "tools": [A_READ_TOOL],
        },
        headers={"x-api-key": "k"},
    )

    assert r.status_code == 200
    body = r.json()
    assert [b["name"] for b in body["content"] if b["type"] == "tool_use"] == ["Read"]
    assert body["stop_reason"] == "tool_use"
    assert fake.answer_turns == []


# --- the router's "no" is a verdict, not a shortfall --------------------------

DECLINED = "NO_TOOL_NEEDED"
ANSWER = "4"


def _streamed_content(response) -> str:
    return "".join(
        json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    )


def test_a_declined_verdict_is_not_reported_as_an_ignored_contract(tmp_path):
    """Live regression, 2026-08-19: the router correctly answered NO_TOOL_NEEDED,
    the tone then answered the question perfectly, and the reply still carried
    "不支持本地工具调用：本轮声明的 1 个工具被忽略" plus advice to switch models."""
    fake = FakeClient(DECLINED, ANSWER)
    r = _chat(_app(tmp_path, fake), UNSUPPORTED_MODEL)

    content = r.json()["choices"][0]["message"]["content"]
    assert content == ANSWER, "the verdict marker must be stripped, not delivered"
    assert "不支持" not in content
    # The verdict costs the answer turn it saved nothing on -- that is the deal.
    assert len(fake.router_turns) == 1 and len(fake.answer_turns) == 1


def test_a_declined_verdict_survives_the_streaming_path(tmp_path):
    fake = FakeClient(DECLINED, ANSWER)
    r = _chat(_app(tmp_path, fake), UNSUPPORTED_MODEL, stream=True)

    assert _streamed_content(r) == ANSWER
    assert DECLINED not in r.text


def test_a_declined_verdict_answers_a_demanded_call_precisely(tmp_path):
    fake = FakeClient(DECLINED, ANSWER)
    r = _chat(_app(tmp_path, fake), UNSUPPORTED_MODEL, tool_choice="required")

    assert r.status_code == 400
    # "the tone ignores our contract" would be the wrong diagnosis here: it read
    # the tools and judged them unnecessary, so switching models need not help.
    assert "明确判断本轮不需要任何工具" in json.dumps(r.json(), ensure_ascii=False)


def test_an_empty_answer_is_not_dressed_up_as_a_verdict(tmp_path):
    """A blank answer turn is a malformed turn; the marker must not become the reply."""
    fake = FakeClient(DECLINED, "")
    r = _chat(_app(tmp_path, fake), UNSUPPORTED_MODEL)

    content = r.json()["choices"][0]["message"]["content"]
    assert DECLINED not in content
    # Routed turn, so the note talks about the router rather than recommending
    # another model -- but it still says the declared tool produced no call.
    assert "工具路由器" in content and "1 个工具没有被调用" in content


# --- it must not make anything worse ------------------------------------------

def test_a_tone_that_honours_the_contract_pays_no_extra_turn(tmp_path):
    fake = FakeClient(DECISION, '```tool_call\n{"name": "Read", "arguments": {"file_path": "/tmp/a.txt"}}\n```')
    r = _chat(_app(tmp_path, fake), VERIFIED_MODEL)

    assert [tc["function"]["name"] for tc in r.json()["choices"][0]["message"]["tool_calls"]] == ["Read"]
    assert fake.router_turns == []


def test_a_failed_classification_turn_falls_back_to_an_ordinary_answer(tmp_path):
    fake = FakeClient(DECISION, PROSE, fail_router=True)
    r = _chat(_app(tmp_path, fake), UNSUPPORTED_MODEL)

    assert r.status_code == 200, "a planning optimisation must never fail the request"
    assert PROSE in r.json()["choices"][0]["message"]["content"]
    assert len(fake.answer_turns) == 1
    # A fallback answer is not a verdict: no usable routing decision was produced
    # and the answer carried no call, which is exactly what the note describes.
    assert "工具路由器" in r.json()["choices"][0]["message"]["content"]


def test_router_can_fall_back_to_next_planner_when_inline_answer_has_no_call():
    fake = FakeClient("unreadable router decision", PROSE)
    calls = []

    async def next_planner():
        calls.append("studio")
        return "studio tool call"

    result = asyncio.run(
        routed_or_answered(
            fake,
            ROUTER_MARKER,
            "ordinary prompt",
            [],
            should_fallback=lambda text: "tool_call" not in text,
            fallback_turn=next_planner,
        )
    )

    assert result == "studio tool call"
    assert calls == ["studio"]


def test_router_stream_can_fall_back_to_next_planner_when_inline_answer_has_no_call():
    fake = FakeClient("unreadable router decision", PROSE)
    calls = []

    async def next_planner():
        calls.append("studio")
        yield "studio tool call"

    async def run():
        return [
            chunk
            async for chunk in routed_or_streamed(
                fake,
                ROUTER_MARKER,
                "ordinary prompt",
                [],
                should_fallback=lambda text: "tool_call" not in text,
                fallback_turn=next_planner,
            )
        ]

    assert asyncio.run(run()) == ["studio tool call"]
    assert calls == ["studio"]


def test_native_mode_switches_the_router_off(tmp_path):
    fake = FakeClient(DECISION, PROSE)
    r = _chat(_app(tmp_path, fake, tool_planning_mode="native"), UNSUPPORTED_MODEL)

    assert fake.router_turns == []
    assert PROSE in r.json()["choices"][0]["message"]["content"]


def test_router_mode_forces_it_on_a_verified_tone(tmp_path):
    fake = FakeClient(DECISION, PROSE)
    _chat(_app(tmp_path, fake, tool_planning_mode="router"), VERIFIED_MODEL)

    assert len(fake.router_turns) == 1


def test_the_setting_persists_and_rejects_a_typo(tmp_path):
    # Own app: the admin routes need an unset admin secret, and the API key the
    # chat tests above authenticate with doubles as that secret.
    client = TestClient(create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD="")))
    assert client.app.state.tool_planning_mode == "auto"

    saved = client.post("/admin/runtime-settings", json={"tool_planning_mode": "router"})
    assert saved.status_code == 200 and saved.json()["settings"]["tool_planning_mode"] == "router"
    # Applied live, not on the next boot: the routes read this per turn.
    assert client.app.state.tool_planning_mode == "router"
    assert client.get("/admin/runtime-settings").json()["settings"]["tool_planning_mode"] == "router"

    bad = client.post("/admin/runtime-settings", json={"tool_planning_mode": "rooter"})
    assert bad.status_code == 400
    assert "studio" in bad.json()["error"]["message"]
    # A rejected save must leave the working value in place.
    assert client.app.state.tool_planning_mode == "router"


# --- Consumer: same router, its own prompt ceiling ----------------------------

class _FakeConsumer:
    """The raw Consumer client shape, so ConsumerClientAdapter runs for real.

    The adapter is what enforces the prompt budget, and that enforcement is the
    only reason the router needs no size handling of its own -- a fake that stood
    in for the adapter would prove nothing about the ceiling.
    """

    def __init__(self, decision: str, answer: str):
        self.mode = "smart"
        self.decision = decision
        self.answer = answer
        self.prompts: list[str] = []

    async def chat_stream(self, prompt, conversation_id="", images=None):
        self.prompts.append(prompt)
        yield self.decision if ROUTER_MARKER in prompt else self.answer

    @property
    def router_prompts(self) -> list[str]:
        return [p for p in self.prompts if ROUTER_MARKER in p]


def _consumer_app(tmp_path, fake: _FakeConsumer, **state):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="k", ADMIN_PASSWORD=""))
    account = app.state.account_store.add(name="Consumer")
    app.state.account_store.set_consumer_auth(
        account.id, cookies=[], access_token="consumer-token",
    )
    key = app.state.key_store.add(name="Consumer Key", account_id=account.id)
    app.state.consumer_client_factory = lambda **kwargs: fake
    for name, value in state.items():
        setattr(app.state, name, value)
    return TestClient(app), key.key


def test_a_consumer_turn_is_routed_within_its_prompt_ceiling(tmp_path):
    """Consumer was excluded from the router over its hard prompt ceiling.

    Measured 2026-08-19: mode smart honoured the native contract 1 time in 6, so
    it is exactly the case the router exists for. The ceiling objection does not
    hold either -- ConsumerClientAdapter compacts anything over the budget, which
    is why build_router_prompt has no size logic of its own.
    """
    fake = _FakeConsumer(DECISION, PROSE)
    client, key = _consumer_app(tmp_path, fake)
    client.app.state.settings.consumer_prompt_max_chars = 1500
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "copilot",
            "messages": [{"role": "user", "content": "读一下 /tmp/a.txt " + "背景 " * 2000}],
            "tools": [READ_TOOL],
        },
        headers={"Authorization": f"Bearer {key}"},
    )

    assert r.status_code == 200
    calls = r.json()["choices"][0]["message"]["tool_calls"]
    assert [c["function"]["name"] for c in calls] == ["Read"]
    assert len(fake.router_prompts) == 1
    assert len(fake.router_prompts[0]) <= 1500, "the adapter must cap the router turn too"


def test_native_mode_leaves_a_consumer_turn_unrouted(tmp_path):
    fake = _FakeConsumer(DECISION, PROSE)
    client, key = _consumer_app(tmp_path, fake, tool_planning_mode="native")
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "copilot",
            "messages": [{"role": "user", "content": "读一下 /tmp/a.txt"}],
            "tools": [READ_TOOL],
        },
        headers={"Authorization": f"Bearer {key}"},
    )

    assert fake.router_prompts == []
    assert PROSE in r.json()["choices"][0]["message"]["content"]
