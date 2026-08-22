from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI, HTTPException

from m365_copilot_openai_proxy.account_concurrency import (
    AccountConcurrency,
    ThrottledClient,
)
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.dependencies import create_api_dependencies
from m365_copilot_openai_proxy.state_init import init_app_state
from m365_copilot_openai_proxy.substrate_client import (
    SIGNALR_SEP,
    SubstrateCopilotClient,
    SubstrateCopilotError,
    SubstrateThrottled,
)
from m365_copilot_openai_proxy.studio_planner import (
    PlannerTurn,
    ordered_or_answered,
    ordered_or_streamed,
    planned_or_answered,
    planned_or_streamed,
)


class ScriptedClient:
    def __init__(self, events):
        self.events = list(events)
        self.calls = []

    async def chat_stream(self, prompt, additional_context, session=None, images=None):
        self.calls.append((prompt, additional_context, session, images))
        for event in self.events:
            if isinstance(event, BaseException):
                raise event
            yield event


def _wire_client(agent_id: str = "") -> SubstrateCopilotClient:
    client = object.__new__(SubstrateCopilotClient)
    client._token = "token"
    client._oid = "object-id"
    client._tid = "tenant-id"
    client._tone = "Magic"
    client._extra_tool_prompt = ""
    client._time_zone = "Asia/Shanghai"
    client._studio_agent_id = agent_id
    return client


def _wire_payload(agent_id: str = "") -> dict:
    encoded = _wire_client(agent_id)._chat_invoke(
        "hello",
        "conversation-id",
        "session-id",
        "request-id",
        True,
    )
    return json.loads(encoded.rstrip(SIGNALR_SEP))


def test_studio_payload_changes_only_agent_attachment_fields():
    ordinary = _wire_payload()
    studio = _wire_payload("title.bot.gpt.default")

    expected = json.loads(json.dumps(ordinary))
    arguments = expected["arguments"][0]
    arguments["threadLevelGptId"] = {
        "id": "title.bot.gpt.default",
        "source": "MOS3",
    }
    arguments["gpts"] = [
        {
            "id": "title.bot.gpt.default",
            "source": "MOS3",
            "version": "1.0.0",
            "clientOverrides": {
                "capabilities": [],
                "deepResearchModels@odata.type": "Collection(String)",
            },
        }
    ]
    arguments.pop("plugins")

    assert studio == expected


def test_studio_websocket_url_targets_agent_surface_with_runtime_id():
    client = _wire_client("title.bot.gpt.default")

    query = parse_qs(urlsplit(client._ws_url("conversation-id", "session-id", "request-id")).query)

    assert query["gptId"] == ["title.bot.gpt.default"]
    assert query["agent"] == ["Agent"]


def test_ordinary_websocket_url_keeps_web_surface_without_runtime_id():
    client = _wire_client()

    query = parse_qs(urlsplit(client._ws_url("conversation-id", "session-id", "request-id")).query)

    assert "gptId" not in query
    assert query["agent"] == ["web"]


def test_empty_studio_agent_id_keeps_builtin_payload():
    arguments = _wire_payload()["arguments"][0]

    assert arguments["threadLevelGptId"] == {}
    assert "gpts" not in arguments
    assert arguments["plugins"] == [
        {"Id": "BingWebSearch", "Source": "BuiltIn"}
    ]


def _dependency_app(tmp_path, factory):
    app = FastAPI()
    app.state.settings = Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key")
    app.state.copilot_client_factory = factory
    return app


def _m365_request():
    account = SimpleNamespace(id="acct-1", provider="m365", token="substrate-token")
    key = SimpleNamespace(
        tone="Magic",
        tool_prompt="",
        time_zone="",
        ws_idle_timeout_minutes=0,
    )
    return SimpleNamespace(state=SimpleNamespace(account=account, api_key_obj=key))


def test_dependency_factory_forwards_explicit_studio_agent_id(tmp_path):
    seen = []

    def factory(**kwargs):
        seen.append(kwargs)
        return ScriptedClient(["studio"])

    app = _dependency_app(tmp_path, factory)
    get_client = create_api_dependencies(app)[1]

    get_client(_m365_request(), studio_agent_id="title.bot.gpt.default")

    assert seen[0]["studio_agent_id"] == "title.bot.gpt.default"


def test_dependency_ordinary_call_does_not_request_studio_client(tmp_path):
    seen = []

    def factory(**kwargs):
        seen.append(kwargs)
        return ScriptedClient(["ordinary"])

    app = _dependency_app(tmp_path, factory)
    get_client = create_api_dependencies(app)[1]

    get_client(_m365_request())

    assert "studio_agent_id" not in seen[0]


def test_explicit_studio_factory_signature_error_is_not_downgraded(tmp_path):
    calls = []

    def factory(token, tone, tool_prompt, time_zone, idle_timeout):
        calls.append("called")
        return ScriptedClient(["ordinary"])

    app = _dependency_app(tmp_path, factory)
    get_client = create_api_dependencies(app)[1]

    with pytest.raises(HTTPException) as error:
        get_client(_m365_request(), studio_agent_id="title.bot.gpt.default")

    assert error.value.status_code == 503
    assert calls == []


def test_default_factory_forwards_studio_agent_id(monkeypatch, tmp_path):
    seen = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs

    import m365_copilot_openai_proxy.state_init as state_init_module

    monkeypatch.setattr(state_init_module, "SubstrateCopilotClient", FakeClient)
    app = FastAPI()
    init_app_state(app, Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    app.state.copilot_client_factory(
        token="substrate-token",
        tone="Magic",
        tool_prompt="",
        time_zone="Asia/Shanghai",
        studio_agent_id="title.bot.gpt.default",
    )

    assert seen["kwargs"]["studio_agent_id"] == "title.bot.gpt.default"


async def _answer(studio_events, fallback):
    return await planned_or_answered(
        studio_turn=PlannerTurn(ScriptedClient(studio_events), "prompt", []),
        fallback_turn=fallback,
    )


def test_answer_falls_back_once_on_zero_output_substrate_error():
    calls = 0

    async def fallback():
        nonlocal calls
        calls += 1
        return "router answer"

    assert asyncio.run(_answer([SubstrateCopilotError("studio failed")], fallback)) == (
        "router answer"
    )
    assert calls == 1


def test_answer_does_not_turn_throttled_into_router_fallback():
    calls = 0

    async def fallback():
        nonlocal calls
        calls += 1
        return "router answer"

    with pytest.raises(SubstrateThrottled, match="throttled"):
        asyncio.run(_answer([SubstrateThrottled("throttled")], fallback))
    assert calls == 0


def test_stream_does_not_turn_throttled_into_router_fallback():
    calls = 0

    async def fallback_stream():
        nonlocal calls
        calls += 1
        yield "router"

    async def run():
        stream = planned_or_streamed(
            studio_turn=PlannerTurn(
                ScriptedClient([SubstrateThrottled("throttled")]),
                "prompt",
                [],
            ),
            fallback_turn=fallback_stream,
        )
        with pytest.raises(SubstrateThrottled, match="throttled"):
            await anext(stream)

    asyncio.run(run())
    assert calls == 0


def test_answer_keeps_fallback_lazy_when_studio_succeeds():
    async def forbidden_fallback():
        raise AssertionError("fallback evaluated eagerly")

    assert asyncio.run(_answer(["stu", "dio"], forbidden_fallback)) == "studio"


def test_answer_does_not_fallback_after_any_studio_delta():
    calls = 0

    async def fallback():
        nonlocal calls
        calls += 1
        return "duplicate"

    with pytest.raises(SubstrateCopilotError, match="late failure"):
        asyncio.run(
            _answer(
                ["partial", SubstrateCopilotError("late failure")],
                fallback,
            )
        )
    assert calls == 0


def test_answer_empty_chunk_does_not_block_zero_output_fallback():
    calls = 0

    async def fallback():
        nonlocal calls
        calls += 1
        return "router answer"

    assert asyncio.run(
        _answer(["", SubstrateCopilotError("studio failed")], fallback)
    ) == "router answer"
    assert calls == 1


def test_answer_falls_back_when_studio_returns_no_tool_call():
    calls = 0

    async def fallback():
        nonlocal calls
        calls += 1
        return "router tool call"

    assert asyncio.run(
        planned_or_answered(
            studio_turn=PlannerTurn(
                ScriptedClient(["plain studio answer"]), "prompt", []
            ),
            fallback_turn=fallback,
            should_fallback=lambda text: "tool_call" not in text,
        )
    ) == "router tool call"
    assert calls == 1


@pytest.mark.parametrize(
    ("script", "predicate", "expected_reason"),
    [
        ([SubstrateCopilotError("studio failed")], None, "upstream_error"),
        (["plain studio answer"], lambda _text: True, "no_tool_call"),
    ],
)
def test_answer_reports_why_studio_fell_back(script, predicate, expected_reason):
    reasons: list[str] = []

    async def fallback():
        return "router"

    result = asyncio.run(
        planned_or_answered(
            studio_turn=PlannerTurn(ScriptedClient(script), "prompt", []),
            fallback_turn=fallback,
            should_fallback=predicate,
            on_fallback=reasons.append,
        )
    )

    assert result == "router"
    assert reasons == [expected_reason]


def test_stream_falls_back_when_studio_returns_no_tool_call():
    calls = 0

    async def fallback_stream():
        nonlocal calls
        calls += 1
        yield "router tool call"

    async def run():
        return [
            chunk
            async for chunk in planned_or_streamed(
                studio_turn=PlannerTurn(
                    ScriptedClient(["plain studio answer"]), "prompt", []
                ),
                fallback_turn=fallback_stream,
                should_fallback=lambda text: "tool_call" not in text,
            )
        ]

    assert asyncio.run(run()) == ["router tool call"]
    assert calls == 1


def test_stream_falls_back_on_zero_output_substrate_error():
    calls = 0

    async def fallback_stream():
        nonlocal calls
        calls += 1
        yield "router-1"
        yield "router-2"

    async def run():
        return [
            chunk
            async for chunk in planned_or_streamed(
                studio_turn=PlannerTurn(
                    ScriptedClient([SubstrateCopilotError("studio failed")]),
                    "prompt",
                    [],
                ),
                fallback_turn=fallback_stream,
            )
        ]

    assert asyncio.run(run()) == ["router-1", "router-2"]
    assert calls == 1


def test_stream_empty_chunk_does_not_block_zero_output_fallback():
    calls = 0

    async def fallback_stream():
        nonlocal calls
        calls += 1
        yield "router"

    async def run():
        return [
            chunk
            async for chunk in planned_or_streamed(
                studio_turn=PlannerTurn(
                    ScriptedClient(["", SubstrateCopilotError("studio failed")]),
                    "prompt",
                    [],
                ),
                fallback_turn=fallback_stream,
            )
        ]

    assert asyncio.run(run()) == ["", "router"]
    assert calls == 1


def test_stream_does_not_fallback_or_duplicate_after_first_delta():
    calls = 0

    async def forbidden_fallback():
        nonlocal calls
        calls += 1
        yield "duplicate"

    async def run():
        stream = planned_or_streamed(
            studio_turn=PlannerTurn(
                ScriptedClient(["partial", SubstrateCopilotError("late failure")]),
                "prompt",
                [],
            ),
            fallback_turn=forbidden_fallback,
        )
        assert await anext(stream) == "partial"
        with pytest.raises(SubstrateCopilotError, match="late failure"):
            await anext(stream)

    asyncio.run(run())
    assert calls == 0


def test_clean_empty_studio_completion_does_not_fallback():
    calls = 0

    async def fallback():
        nonlocal calls
        calls += 1
        return "router"

    assert asyncio.run(_answer([], fallback)) == ""
    assert calls == 0


def test_programming_error_is_not_converted_to_router_fallback():
    calls = 0

    async def fallback():
        nonlocal calls
        calls += 1
        return "router"

    with pytest.raises(RuntimeError, match="bug"):
        asyncio.run(_answer([RuntimeError("bug")], fallback))
    assert calls == 0


def test_zero_output_fallback_reacquires_throttle_without_deadlock():
    async def run():
        gate = AccountConcurrency()
        studio = ThrottledClient(
            ScriptedClient([SubstrateCopilotError("failed")]),
            lambda: gate.hold("acct-1", 1),
        )
        normal = ThrottledClient(
            ScriptedClient(["router"]),
            lambda: gate.hold("acct-1", 1),
        )

        async def fallback():
            return "".join(
                [chunk async for chunk in normal.chat_stream("normal", [], None)]
            )

        result = await asyncio.wait_for(
            planned_or_answered(
                studio_turn=PlannerTurn(studio, "studio", []),
                fallback_turn=fallback,
            ),
            timeout=0.5,
        )
        assert result == "router"
        assert gate.stats() == {}

    asyncio.run(run())


def test_ordered_answered_studio_mode_is_studio_router_inline():
    calls: list[str] = []

    class Client:
        async def chat_stream(self, *args):
            calls.append("studio")
            yield "plain answer"

    async def router(fallback):
        calls.append("router")
        return await fallback()

    async def inline():
        calls.append("inline")
        return "inline answer"

    result = asyncio.run(
        ordered_or_answered(
            studio_turn=PlannerTurn(Client(), "prompt", []),
            router_turn=router,
            inline_turn=inline,
            prefer_router=False,
            should_fallback=lambda text: True,
        )
    )
    assert result == "inline answer"
    assert calls == ["studio", "router", "inline"]


def test_ordered_answered_router_mode_is_router_studio_inline():
    calls: list[str] = []

    class Client:
        async def chat_stream(self, *args):
            calls.append("studio")
            yield "plain answer"

    async def router(fallback):
        calls.append("router")
        return await fallback()

    async def inline():
        calls.append("inline")
        return "inline answer"

    result = asyncio.run(
        ordered_or_answered(
            studio_turn=PlannerTurn(Client(), "prompt", []),
            router_turn=router,
            inline_turn=inline,
            prefer_router=True,
            should_fallback=lambda text: True,
        )
    )
    assert result == "inline answer"
    assert calls == ["router", "studio", "inline"]


def test_ordered_answered_reports_each_entered_stage():
    stages: list[str] = []

    class Client:
        async def chat_stream(self, *args):
            yield "plain answer"

    async def router(fallback):
        return await fallback()

    async def inline():
        return "inline answer"

    result = asyncio.run(
        ordered_or_answered(
            studio_turn=PlannerTurn(Client(), "prompt", []),
            router_turn=router,
            inline_turn=inline,
            prefer_router=False,
            should_fallback=lambda _text: True,
            on_stage=stages.append,
        )
    )

    assert result == "inline answer"
    assert stages == ["studio", "router", "inline"]


def test_ordered_streamed_reports_each_entered_stage():
    stages: list[str] = []

    class Client:
        async def chat_stream(self, *args):
            yield "plain answer"

    async def router(fallback):
        async for chunk in fallback():
            yield chunk

    async def inline():
        yield "inline answer"

    async def run():
        return [
            chunk
            async for chunk in ordered_or_streamed(
                studio_turn=PlannerTurn(Client(), "prompt", []),
                router_turn=router,
                inline_turn=inline,
                prefer_router=False,
                should_fallback=lambda _text: True,
                on_stage=stages.append,
            )
        ]

    assert asyncio.run(run()) == ["inline answer"]
    assert stages == ["studio", "router", "inline"]


def test_ordered_streamed_without_studio_keeps_router_ordinary_answer():
    calls: list[str] = []

    async def router(fallback):
        calls.append("router")
        assert fallback is None
        yield "router answer"

    async def inline():
        pytest.fail("the router owns its ordinary answer when no next planner exists")
        yield  # pragma: no cover

    async def run():
        return [
            chunk
            async for chunk in ordered_or_streamed(
                studio_turn=None,
                router_turn=router,
                inline_turn=inline,
                prefer_router=True,
            )
        ]

    assert asyncio.run(run()) == ["router answer"]
    assert calls == ["router"]
